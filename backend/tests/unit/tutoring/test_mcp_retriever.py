from typing import Any

import pytest

from fakes import FakeTokenVerifier, InMemoryLibrary, fake_embeddings, in_process_mcp, ingest_ready
from fakes.mcp import MCP_TEST_URL
from smart_tutor.apps.mcp_server.server import build_server
from smart_tutor.knowledge.application import SearchService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.domain.errors import RetrievalError


def build(library: InMemoryLibrary, verifier: FakeTokenVerifier) -> Any:
    return build_server(Settings(), verifier, SearchService(library.unit_of_work, fake_embeddings()))


def verifier_for_ada() -> FakeTokenVerifier:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "ada", frozenset({"learner"})))
    return verifier


async def test_returns_retrieved_chunks_for_the_tokens_learner() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.")
    async with in_process_mcp(build(library, verifier_for_ada())) as transport:
        retriever = McpRetriever(MCP_TEST_URL, "t-ada", transport)
        [found] = await retriever.search("Attention is all you need.", [GENERAL_SUBJECT_ID])
    assert found.text == "Attention is all you need."
    assert found.page == 1
    assert found.document_title.endswith(".pdf")


async def test_a_refused_token_raises_unauthenticated() -> None:
    async with in_process_mcp(build(InMemoryLibrary(), FakeTokenVerifier())) as transport:
        retriever = McpRetriever(MCP_TEST_URL, "t-unknown", transport)
        with pytest.raises(UnauthenticatedError):
            await retriever.search("q", [GENERAL_SUBJECT_ID])


async def test_a_tool_error_raises_retrieval_error() -> None:
    async with in_process_mcp(build(InMemoryLibrary(), verifier_for_ada())) as transport:
        retriever = McpRetriever(MCP_TEST_URL, "t-ada", transport)
        with pytest.raises(RetrievalError):
            await retriever.search("  ", [GENERAL_SUBJECT_ID])


def test_repr_never_shows_the_token() -> None:
    assert "t-secret" not in repr(McpRetriever(MCP_TEST_URL, "t-secret"))
    assert "t-secret" not in str(vars(McpRetriever(MCP_TEST_URL, "t-secret")).keys())
