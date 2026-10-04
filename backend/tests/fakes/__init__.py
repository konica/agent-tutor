"""Fake adapters for unit tests: services get these through their constructors instead of real ones."""

from fakes.auth import FakeTokenVerifier
from fakes.clock import FixedClock
from fakes.knowledge import FakeObjectStore, InMemoryLibrary
from fakes.models import FakeChatModel, fake_chat_model, fake_embeddings

__all__ = [
    "FakeChatModel",
    "fake_chat_model",
    "fake_embeddings",
    "FakeTokenVerifier",
    "FixedClock",
    "InMemoryLibrary",
    "FakeObjectStore",
]
