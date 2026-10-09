"""Retriever over the RAG MCP server's `search` tool (ADR 0007: the token rides in the Authorization header)."""

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT, MCP_DEFAULT_TIMEOUT

from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.ports.retriever import Retriever


class McpRetriever(Retriever):
    """One per request: holds that request's token, which never appears in repr or errors."""

    def __init__(self, url: str, access_token: str, transport: httpx2.AsyncBaseTransport | None = None) -> None:
        self._url = url
        self.__token = access_token  # name-mangled and left out of __repr__
        self._transport = transport

    def __repr__(self) -> str:
        return f"McpRetriever(url={self._url!r})"

    async def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        refused = False

        async def note_401(response: httpx2.Response) -> None:
            nonlocal refused
            refused = refused or response.status_code == 401

        try:
            async with (
                httpx2.AsyncClient(
                    transport=self._transport,
                    timeout=httpx2.Timeout(MCP_DEFAULT_TIMEOUT, read=MCP_DEFAULT_SSE_READ_TIMEOUT),
                    headers={"Authorization": f"Bearer {self.__token}"},
                    event_hooks={"response": [note_401]},
                ) as http,
                Client(streamable_http_client(self._url, http_client=http)) as client,
            ):
                result = await client.call_tool("search", {"query": query, "k": k})
        except BaseException as e:  # the SDK wraps transport errors in ExceptionGroups
            if not isinstance(e, Exception):
                raise  # cancellation, interrupts and BaseExceptionGroups holding them propagate as-is
            if refused:
                raise UnauthenticatedError("search refused the token") from None
            raise RetrievalError(f"search failed: {type(e).__name__}") from None
        if result.is_error or not result.structured_content:
            raise RetrievalError("search returned an error")
        return [
            RetrievedChunk(c["chunk_id"], c["document_title"], c["page"], c["text"], c["score"])
            for c in result.structured_content["chunks"]
        ]
