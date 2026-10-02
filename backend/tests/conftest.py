"""Shared fixtures. Unit tests use fakes; integration tests (marker `integration`) need `make up`."""

import pytest

from fakes import FakeEmbeddingModel


@pytest.fixture
def embedding_model() -> FakeEmbeddingModel:
    return FakeEmbeddingModel()
