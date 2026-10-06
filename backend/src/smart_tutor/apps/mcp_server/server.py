"""RAG MCP server: streamable HTTP at :8000/mcp (SMART_TUTOR_MCP_PORT; 10452 on the host).

Every HTTP request's bearer token is introspected by Keycloak as the rag-mcp client (ADR 0007). Tools take no
user id: the caller comes from the verified token, and search filters with `can_read` in SQL (PRD §9.3).
"""

import asyncio
import logging

import httpx
from mcp.server import MCPServer
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from pydantic import AnyHttpUrl, BaseModel

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import InvalidSearchError, SearchService
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.ports.token_verifier import TokenVerifier

logger = logging.getLogger(__name__)


class ChunkResult(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None
    text: str
    score: float


class SearchResponse(BaseModel):
    chunks: list[ChunkResult]


class IntrospectionBridge:
    """The SDK's TokenVerifier hook on top of ours; None makes the SDK answer 401."""

    def __init__(self, verifier: TokenVerifier) -> None:
        self._verifier = verifier

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            principal = await self._verifier.verify(token)
        except UnauthenticatedError as e:
            logger.info("rejected MCP request: %s", e)  # the reason only, never the token
            return None
        return AccessToken(token=token, client_id="smart-tutor-web", scopes=[], subject=principal.user_id)


def build_server(settings: Settings, verifier: TokenVerifier, search: SearchService) -> MCPServer:
    mcp = MCPServer(
        "rag-mcp",
        token_verifier=IntrospectionBridge(verifier),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.keycloak_issuer),
            resource_server_url=AnyHttpUrl(settings.mcp_url),
            validate_token_resource=False,  # the verifier checks aud=rag-mcp itself
        ),
    )

    @mcp.tool(name="search")
    async def search_tool(query: str, subject_ids: list[str], k: int = 5) -> SearchResponse:
        """Chunks of the caller's ready documents in any of these subjects, nearest first."""
        token = get_access_token()
        if token is None or not token.subject:
            raise ValueError("not authenticated")
        try:
            hits = await asyncio.to_thread(
                search.search, UserId(token.subject), query, [SubjectId(s) for s in subject_ids], k
            )
        except InvalidSearchError as e:
            raise ValueError(str(e)) from None
        return SearchResponse(
            chunks=[
                ChunkResult(
                    chunk_id=h.chunk_id,
                    document_id=str(h.document_id),
                    document_title=h.document_title,
                    page=h.page,
                    text=h.text,
                    score=h.score,
                )
                for h in hits
            ]
        )

    return mcp


def _search_service(settings: Settings) -> SearchService:
    engine = create_db_engine(settings.database_url)
    return SearchService(lambda: SqlLibraryUnitOfWork(engine), ModelFactory(settings).embedding())


def main() -> None:
    settings = Settings()
    if not settings.keycloak_client_secret.get_secret_value():
        raise RuntimeError("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET is not set")
    verifier = keycloak_verifier(settings, httpx.AsyncClient(timeout=5))
    build_server(settings, verifier, _search_service(settings)).run(
        transport="streamable-http", host="0.0.0.0", port=settings.mcp_port
    )


if __name__ == "__main__":
    main()
