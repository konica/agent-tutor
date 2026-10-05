"""Fake adapters for unit tests: services get these through their constructors instead of real ones."""

from fakes.auth import FakeTokenVerifier
from fakes.clock import FixedClock
from fakes.knowledge import FakeObjectStore, InMemoryLibrary
from fakes.models import FakeChatModel, fake_chat_model, fake_embeddings
from fakes.parameters import TEST_LIMITS, FakeParameterStore
from fakes.pdfs import make_pdf
from fakes.processing import FakePdfExtractor, PageChunker, fake_tools
from fakes.queue import FakeQueue
from fakes.subjects import InMemorySubjects

__all__ = [
    "FakeChatModel",
    "fake_chat_model",
    "fake_embeddings",
    "FakeTokenVerifier",
    "FixedClock",
    "InMemoryLibrary",
    "InMemorySubjects",
    "FakeObjectStore",
    "FakeQueue",
    "FakePdfExtractor",
    "PageChunker",
    "fake_tools",
    "make_pdf",
    "FakeParameterStore",
    "TEST_LIMITS",
]
