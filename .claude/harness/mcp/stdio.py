"""StdioServer: MCP over stdio, one JSON-RPC 2.0 message per line: initialize, tools/list, tools/call, ping.
A tool that fails answers an error result the model reads; a wrong request answers a JSON-RPC error."""
import json

PROTOCOL = "2025-06-18"
PARSE, NO_METHOD, BAD_PARAMS = -32700, -32601, -32602


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
            except ValueError as e:
                answer = StdioServer.error(None, PARSE, f"not JSON: {e}")
            else:
                answer = self.handle(message)
            if answer is not None:
                outstream.write(json.dumps(answer, ensure_ascii=False) + "\n")
                outstream.flush()

    def handle(self, message):
        if not isinstance(message, dict):
            return StdioServer.error(None, BAD_PARAMS, "a message is an object")
        id, method, params = message.get("id"), message.get("method"), message.get("params") or {}
        if id is None:
            return None  # a notification
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
        tool = self.tools.get(params.get("name"))
        if tool is None:
            return StdioServer.error(id, BAD_PARAMS, f"no tool {params.get('name')}")
        try:
            result = tool.call(params.get("arguments") or {})
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
