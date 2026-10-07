"""US-12: detection scores come only from the learner's own documents, even in a shared subject."""

from collections.abc import Mapping

from fakes import FakeTokenVerifier, InMemoryLibrary, fake_embeddings, in_process_mcp, ingest_ready
from fakes.mcp import MCP_TEST_URL
from smart_tutor.apps.mcp_server import server
from smart_tutor.knowledge.application import SearchService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import DetectionPolicy, SubjectDetector

S1 = SubjectId("00000000-0000-4000-8000-0000000000c1")
S2 = SubjectId("00000000-0000-4000-8000-0000000000c2")  # shared by both learners
QUESTION = "Photosynthesis makes glucose."
POLICY = DetectionPolicy(detect_threshold=0.35, detect_margin=0.05, multi_margin=0.03)


async def a_scores(with_b: bool) -> Mapping[SubjectId, float]:
    library = InMemoryLibrary()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=[S1])
    ingest_ready(library, "learner-a", "Gradient descent follows the slope.", subject_ids=[S2])
    if with_b:
        ingest_ready(library, "learner-b", QUESTION, subject_ids=[S2])  # would score 1.0 in S2 if it leaked
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "a", frozenset({"learner"})))
    mcp = server.build_server(Settings(), verifier, SearchService(library.unit_of_work, fake_embeddings()))
    async with in_process_mcp(mcp) as transport:
        retriever = McpRetriever(MCP_TEST_URL, "token-a", transport=transport)
        detection = await SubjectDetector(retriever, POLICY).detect(QUESTION, [S1, S2])
    return detection.scores


async def test_another_learners_chunks_in_a_shared_subject_never_change_the_scores() -> None:
    alone, together = await a_scores(with_b=False), await a_scores(with_b=True)
    assert together == alone
    assert set(together) == {S1, S2} and together[S2] < 0.999
