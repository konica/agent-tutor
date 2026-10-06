"""RAG MCP server: introspected token, caller from the token only, typed results."""

from typing import Any

import httpx2
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from fakes import FakeTokenVerifier, InMemoryLibrary, fake_embeddings, in_process_mcp, ingest_ready
from fakes.mcp import MCP_TEST_URL
from smart_tutor.apps.mcp_server import server
from smart_tutor.knowledge.application import SearchService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

GENERAL = str(GENERAL_SUBJECT_ID)


def build(library: InMemoryLibrary, verifier: FakeTokenVerifier) -> Any:
    return server.build_server(Settings(), verifier, SearchService(library.unit_of_work, fake_embeddings()))


async def call_search(mcp: Any, token: str, **arguments: Any) -> Any:
    async with (
        in_process_mcp(mcp) as transport,
        httpx2.AsyncClient(transport=transport, headers={"Authorization": f"Bearer {token}"}) as http,
        Client(streamable_http_client(MCP_TEST_URL, http_client=http)) as client,
    ):
        return await client.call_tool("search", arguments)


async def raw_post(mcp: Any, headers: dict[str, str]) -> int:
    async with in_process_mcp(mcp) as transport, httpx2.AsyncClient(transport=transport) as http:
        return (await http.post(MCP_TEST_URL, json={}, headers=headers)).status_code


def verifier_with(token: str, user: str) -> FakeTokenVerifier:
    verifier = FakeTokenVerifier()
    verifier.add(token, Principal(UserId(user), user, frozenset({"learner"})))
    return verifier


async def test_search_returns_the_callers_chunks_as_structured_content() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.")
    result = await call_search(
        build(library, verifier_with("t-ada", "ada")),
        "t-ada",
        query="Attention is all you need.",
        subject_ids=[GENERAL],
    )
    assert not result.is_error
    [chunk] = result.structured_content["chunks"]
    assert chunk["text"] == "Attention is all you need." and chunk["page"] == 1


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer unknown"}, {"Authorization": "Basic x"}])
async def test_no_or_bad_token_is_401(headers: dict[str, str]) -> None:
    assert await raw_post(build(InMemoryLibrary(), verifier_with("t-ada", "ada")), headers) == 401


async def test_a_revoked_token_is_401() -> None:
    verifier = verifier_with("t-ada", "ada")
    verifier.revoke("t-ada")
    assert await raw_post(build(InMemoryLibrary(), verifier), {"Authorization": "Bearer t-ada"}) == 401


@pytest.mark.parametrize(("query", "subject_ids", "reason"), [(" ", [GENERAL], "query"), ("q", ["not-a-uuid"], "UUID")])
async def test_invalid_arguments_are_a_tool_error_with_the_reason(
    query: str, subject_ids: list[str], reason: str
) -> None:
    result = await call_search(
        build(InMemoryLibrary(), verifier_with("t", "ada")), "t", query=query, subject_ids=subject_ids
    )
    assert result.is_error
    assert reason in result.content[0].text


async def test_the_tool_takes_no_user_id() -> None:
    mcp = build(InMemoryLibrary(), verifier_with("t", "ada"))
    [tool] = [t for t in await mcp.list_tools() if t.name == "search"]
    assert set(tool.input_schema["properties"]) == {"query", "subject_ids", "k"}


def test_main_listens_on_the_configured_port(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(server.MCPServer, "run", lambda self, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        server, "_search_service", lambda settings: SearchService(InMemoryLibrary().unit_of_work, fake_embeddings())
    )
    monkeypatch.setenv("SMART_TUTOR_MCP_PORT", "10452")
    monkeypatch.setenv("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET", "s")
    server.main()
    assert calls == [{"transport": "streamable-http", "host": "0.0.0.0", "port": 10452}]


def test_main_refuses_to_start_without_a_client_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="KEYCLOAK_CLIENT_SECRET"):
        server.main()
