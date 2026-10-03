"""Shared fixtures. Unit tests use fakes; integration tests (marker `integration`) need `make up`."""

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from fakes import fake_embeddings


@pytest.fixture
def embedding_model() -> DeterministicFakeEmbedding:
    return fake_embeddings()
