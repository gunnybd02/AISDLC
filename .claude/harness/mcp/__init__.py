"""Block mcp: what the model calls (the MCP server, its tools). It decides nothing."""
ITEMS = [
    {"kind": "server", "name": "stdio", "ref": "harness.mcp.stdio:StdioServer"},
    {"kind": "table", "name": "action_table", "ref": "harness.mcp.actions:ActionTable"},
    {"kind": "source", "name": "skills", "ref": "harness.mcp.skills:Skills"},
    {"kind": "tool", "name": "find", "ref": "harness.mcp.find_tool:Find"},
    {"kind": "tool", "name": "guide", "ref": "harness.mcp.guide_tool:Guide"},
    {"kind": "tool", "name": "run", "ref": "harness.mcp.run_tool:Run"},
]
