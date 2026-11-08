"""StdioServer: MCP over stdio, one JSON-RPC 2.0 message per line: initialize, tools/list, tools/call, ping.
A tool that fails answers an error result the model reads; a wrong request answers a JSON-RPC error; nothing a client
sends stops the server. Answers are written as ASCII JSON, so any text a client echoes can be written."""
import json

PROTOCOL = "2025-06-18"
PARSE, NO_METHOD, BAD_PARAMS, INTERNAL = -32700, -32601, -32602, -32603


class StdioServer:
    def __init__(self, name, version, tools):
        self.info = {"name": name, "version": version}
        self.tools = {t.name: t for t in tools}

    def serve(self, instream, outstream):
        for line in instream:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except (ValueError, RecursionError) as e:
                answer = StdioServer.error(None, PARSE, f"not JSON: {type(e).__name__}")
            else:
                answer = self.handle(message)
            if answer is not None:
                outstream.write(json.dumps(answer) + "\n")
                outstream.flush()

    def handle(self, message):
        """The answer to one message; a notification gets none. Nothing a client sends stops the server."""
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

    def answer(self, id, method, params):
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

    def call(self, id, params):
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
    def ok(id, result):
        return {"jsonrpc": "2.0", "id": id, "result": result}

    @staticmethod
    def error(id, code, text):
        return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": text}}
