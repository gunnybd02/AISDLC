"""StdioServer: MCP over stdio, one JSON-RPC 2.0 message per line: initialize, tools/list, tools/call, ping.
A tool that fails answers an error result the model reads; a wrong request answers a JSON-RPC error; nothing a client
sends stops the server. Answers are written as ASCII JSON, so any text a client echoes can be written."""
from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Optional, TextIO

if TYPE_CHECKING:
    from harness.mcp.server.tool import Tool

PROTOCOL = "2025-06-18"
PARSE, NO_METHOD, BAD_PARAMS, INTERNAL = -32700, -32601, -32602, -32603

RequestId = Optional[str | int]
"""The id of a JSON-RPC request as the client sent it (None for a notification or a message with no id)."""
Answer = dict[str, Any]
"""A JSON-RPC 2.0 answer: {"jsonrpc": "2.0", "id", "result"} or {"jsonrpc": "2.0", "id", "error": {code, message}}."""


class StdioServer:
    """The MCP server over stdio: it reads one JSON-RPC message per line and writes one answer per line."""

    def __init__(self, name: str, version: str, tools: Iterable[Tool]) -> None:
        """Keep the server's name and version and its tools by name.

        Args:
            name: the server's name in serverInfo.
            version: the server's version in serverInfo.
            tools: the tools it serves (find, guide, run).
        """
        self.info = {"name": name, "version": version}
        self.tools = {t.name: t for t in tools}

    def serve(self, instream: Iterable[str], outstream: TextIO) -> None:
        """Answer every line of instream until it ends.

        Args:
            instream: the client's messages, one JSON-RPC message per line (stdin).
            outstream: where the answers are written, one per line (stdout).
        """
        for line in instream:
            self.serve_line(line, outstream)

    def serve_line(self, line: str, outstream: TextIO) -> None:
        """Answer one line (nothing for a blank line or a notification).

        Args:
            line: one line the client sent.
            outstream: where the answer is written (as one ASCII JSON line, then flushed).
        """
        if not line.strip():
            return
        try:
            message = json.loads(line)
        except (ValueError, RecursionError) as e:
            answer = StdioServer.error(None, PARSE, f"not JSON: {type(e).__name__}")
        else:
            answer = self.handle(message)
        if answer is not None:
            outstream.write(json.dumps(answer) + "\n")
            outstream.flush()

    def handle(self, message: Any) -> Optional[Answer]:
        """The answer to one message; a notification gets none. Nothing a client sends stops the server.

        Args:
            message: the message as parsed from JSON (any JSON value; a request is an object with id, method and
                params).

        Returns:
            The JSON-RPC answer; None for a notification (no id); an error answer for a message that is not an
            object, params that are not an object, or a method that failed.
        """
        if not isinstance(message, dict):
            return StdioServer.error(None, BAD_PARAMS, "a message is an object")
        id, params = message.get("id"), message.get("params", {})
        if id is None:
            return None  # a notification
        if not isinstance(params, dict):
            return StdioServer.error(id, BAD_PARAMS, "params is an object")
        try:
            return self.answer(id, message.get("method"), params)
        except Exception as e:
            return StdioServer.error(id, INTERNAL, f"{type(e).__name__}: {e}")

    def answer(self, id: RequestId, method: Any, params: dict[str, Any]) -> Answer:
        """The answer to one request by its method.

        Args:
            id: the request's id.
            method: the request's method as sent (a known one is a string).
            params: the request's params.

        Returns:
            initialize: the protocol version, the capabilities and serverInfo; ping: {}; tools/list: the listing of
            each tool; tools/call: the tool's result; else a no-method error.
        """
        if method == "initialize":
            return StdioServer.ok(id, {"protocolVersion": params.get("protocolVersion", PROTOCOL),
                                       "capabilities": {"tools": {}}, "serverInfo": self.info})
        if method == "ping":
            return StdioServer.ok(id, {})
        if method == "tools/list":
            return StdioServer.ok(id, {"tools": [t.listing() for t in self.tools.values()]})
        if method == "tools/call":
            return self.call(id, params)
        return StdioServer.error(id, NO_METHOD, f"no method {method}")

    def call(self, id: RequestId, params: dict[str, Any]) -> Answer:
        """Call one tool (tools/call).

        Args:
            id: the request's id.
            params: {"name": the tool, "arguments": its arguments (an object)}.

        Returns:
            A result {"content": [{"type": "text", "text"}], "isError"}: the tool's text, or why it failed (a tool
            that raises is an error result the model reads); an error answer for an unknown tool or arguments that
            are not an object.
        """
        name, arguments = params.get("name"), params.get("arguments", {})
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return StdioServer.error(id, BAD_PARAMS, f"no tool {name}")
        if not isinstance(arguments, dict):
            return StdioServer.error(id, BAD_PARAMS, "arguments is an object")
        try:
            result = tool.call(arguments)
            text, is_error = result.text, result.is_error
        except Exception as e:
            text, is_error = f"{tool.name} failed: {type(e).__name__}: {e}", True
        return StdioServer.ok(id, {"content": [{"type": "text", "text": text}], "isError": is_error})

    @staticmethod
    def ok(id: RequestId, result: dict[str, Any]) -> Answer:
        """A JSON-RPC result answer.

        Args:
            id: the request's id.
            result: the result object.

        Returns:
            {"jsonrpc": "2.0", "id": id, "result": result}.
        """
        return {"jsonrpc": "2.0", "id": id, "result": result}

    @staticmethod
    def error(id: RequestId, code: int, text: str) -> Answer:
        """A JSON-RPC error answer.

        Args:
            id: the request's id (None when it could not be read).
            code: the JSON-RPC error code (PARSE, NO_METHOD, BAD_PARAMS, INTERNAL).
            text: the error's message.

        Returns:
            {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": text}}.
        """
        return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": text}}
