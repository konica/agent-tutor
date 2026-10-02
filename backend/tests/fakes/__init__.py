"""Fake adapters for unit tests: services get these through their constructors instead of real ones."""

from fakes.models import FakeChatModel, FakeEmbeddingModel

__all__ = ["FakeChatModel", "FakeEmbeddingModel"]
