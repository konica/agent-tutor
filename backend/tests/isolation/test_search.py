"""US-12: two learners in the same subject; MCP search never returns the other learner's chunks."""

import json
from typing import Any

import httpx2
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

A_TEXT = "Transformers use self-attention."
B_TEXT = "Photosynthesis makes glucose."


def world() -> tuple[InMemoryLibrary, FakeTokenVerifier, str]:
    library = InMemoryLibrary()
    a_doc = ingest_ready(library, "learner-a", A_TEXT)
    ingest_ready(library, "learner-b", B_TEXT)
    verifier = FakeTokenVerifier()
    for user in ("a", "b"):
        verifier.add(f"token-{user}", Principal(UserId(f"learner-{user}"), user, frozenset({"learner"})))
    return library, verifier, str(a_doc)


async def search_as(library: InMemoryLibrary, verifier: FakeTokenVerifier, token: str, **arguments: Any) -> Any:
    mcp = server.build_server(Settings(), verifier, SearchService(library.unit_of_work, fake_embeddings()))
    async with (
        in_process_mcp(mcp) as transport,
        httpx2.AsyncClient(transport=transport, headers={"Authorization": f"Bearer {token}"}) as http,
        Client(streamable_http_client(MCP_TEST_URL, http_client=http)) as client,
    ):
        return await client.call_tool("search", arguments)


async def test_b_never_gets_as_chunks_in_the_same_subject() -> None:
    library, verifier, a_doc = world()
    result = await search_as(library, verifier, "token-b", query=A_TEXT, subject_ids=[str(GENERAL_SUBJECT_ID)])
    assert not result.is_error
    chunks = result.structured_content["chunks"]
    assert chunks and all(c["text"] == B_TEXT for c in chunks)
    raw = json.dumps(result.structured_content)
    assert A_TEXT not in raw and a_doc not in raw


async def test_a_user_id_argument_changes_nothing() -> None:
    library, verifier, a_doc = world()
    result = await search_as(
        library, verifier, "token-b", query=A_TEXT, subject_ids=[str(GENERAL_SUBJECT_ID)], user_id="learner-a"
    )
    chunks = [] if result.is_error else result.structured_content["chunks"]
    assert all(c["text"] == B_TEXT for c in chunks)
    assert A_TEXT not in json.dumps(chunks) and a_doc not in json.dumps(chunks)
