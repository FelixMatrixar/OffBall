"""The OffBall MCP server (PRD 14.8): match data and exact metrics for agents, and for any MCP client.

Run it on its own with `offball serve mcp`, or mounted in the API at /mcp. Every tool is read-only.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from offball.mcp import tools

INSTRUCTIONS = (
    "OffBall explains off-ball football moments in synthetic matches. Use list_matches to find a match, "
    "list_candidates for the moments found in it, and moment_card for everything about one moment. Quote a "
    "number only if compute_metric returned it, and cite its evidence IDs. All match data is synthetic."
)


def build_server(host: str = "127.0.0.1", port: int = 8001) -> FastMCP:
    server = FastMCP("offball", instructions=INSTRUCTIONS, host=host, port=port, stateless_http=True,
                     json_response=True)
    read_only = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
    for fn in tools.READ_TOOLS:
        server.add_tool(fn, annotations=read_only, structured_output=False)
    return server
