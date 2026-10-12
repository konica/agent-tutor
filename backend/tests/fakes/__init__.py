"""Fake adapters for unit tests: services get these through their constructors instead of real ones."""

from fakes.api import api_services, fake_agent
from fakes.auth import FakeTokenVerifier
from fakes.clock import FixedClock
from fakes.ingest import ingest_ready
from fakes.insights import InMemoryHighlightMisses
from fakes.knowledge import FakeObjectStore, InMemoryLibrary
from fakes.mcp import in_process_mcp
from fakes.models import (
    DESCRIPTION_ARGS,
    FakeChatModel,
    describe_reply,
    describing_chat_model,
    fake_chat_model,
    fake_embeddings,
)
from fakes.parameters import APP_TZ, TEST_LIMITS, TEST_UPLOAD_LIMITS, FakeParameterStore
from fakes.pdfs import make_pdf
from fakes.processing import FakePdfExtractor, PageChunker, fake_tools
from fakes.queue import FakeQueue
from fakes.subjects import InMemorySubjects
from fakes.tracing import META as TRACE_META
from fakes.tracing import (
    FailingExporter,
    FakeRunTracing,
    FeedbackClient,
    InlineExecutor,
    RecordingClient,
    recorded_traces,
)
from fakes.tutoring import FakeAnswerFeedback, FakeRetriever, InMemoryThreads

__all__ = [
    "api_services",
    "fake_agent",
    "DESCRIPTION_ARGS",
    "describe_reply",
    "describing_chat_model",
    "FakeChatModel",
    "FakeAnswerFeedback",
    "FakeRetriever",
    "FailingExporter",
    "FakeRunTracing",
    "RecordingClient",
    "recorded_traces",
    "TRACE_META",
    "FeedbackClient",
    "InlineExecutor",
    "fake_chat_model",
    "fake_embeddings",
    "FakeTokenVerifier",
    "FixedClock",
    "InMemoryHighlightMisses",
    "InMemoryLibrary",
    "InMemorySubjects",
    "InMemoryThreads",
    "FakeObjectStore",
    "FakeQueue",
    "FakePdfExtractor",
    "PageChunker",
    "fake_tools",
    "make_pdf",
    "ingest_ready",
    "in_process_mcp",
    "FakeParameterStore",
    "TEST_LIMITS",
    "TEST_UPLOAD_LIMITS",
    "APP_TZ",
]
