# ruff: noqa
"""Short-lived MCP client sessions for use inside agent-side helper tools.

The McpToolset on the root agent handles the LLM-facing surface; the helpers
in tools.py need to call MCP tools from Python (e.g. wait_for_job polling
get_job_status). They open their own sessions rather than reaching into the
McpToolset's private session manager.
"""

from __future__ import annotations

import contextlib
import json
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from .mcp_auth import IdTokenAuth


@contextlib.asynccontextmanager
async def mcp_session():
    base = os.environ["MCP_SERVER_URL"].rstrip("/")
    async with streamablehttp_client(
        url=f"{base}/mcp",
        timeout=30.0,
        sse_read_timeout=600.0,
        auth=IdTokenAuth(base),
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


async def call_mcp_tool(name: str, arguments: dict) -> dict:
    """Call a single MCP tool and return its structured result."""
    async with mcp_session() as session:
        result = await session.call_tool(name, arguments)
    if result.structuredContent is not None:
        sc = result.structuredContent
        return sc["result"] if "result" in sc and len(sc) == 1 else sc
    text = "".join(c.text for c in result.content if hasattr(c, "text"))
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {"text": text}
