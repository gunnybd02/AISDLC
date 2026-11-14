"""Block mcp: what the model calls (the MCP server, its tools). It decides nothing."""
ITEMS = [
    {"kind": "server", "name": "stdio", "ref": "harness.mcp.server.stdio:StdioServer"},
    {"kind": "table", "name": "action_table", "ref": "harness.mcp.actions.table:ActionTable"},
    {"kind": "source", "name": "skills", "ref": "harness.mcp.skills.library:Skills"},
    {"kind": "tool", "name": "find", "ref": "harness.mcp.tools.find:Find"},
    {"kind": "tool", "name": "guide", "ref": "harness.mcp.tools.guide:Guide"},
    {"kind": "tool", "name": "run", "ref": "harness.mcp.tools.run:Run"},
]
