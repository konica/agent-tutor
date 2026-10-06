"""Serve an MCPServer in-process, so clients talk to it over streamable HTTP without a socket."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
from mcp.server import MCPServer

MCP_TEST_URL = "http://mcp.test/mcp"


@asynccontextmanager
async def in_process_mcp(server: MCPServer) -> AsyncIterator[httpx2.ASGITransport]:
    """A transport to `server`; pass it to an httpx2 client with base URL http://mcp.test. One use per server."""
    app = server.streamable_http_app(host="0.0.0.0")  # not localhost: skips the DNS-rebinding check (421)
    async with server.session_manager.run():
        yield httpx2.ASGITransport(app=app)
