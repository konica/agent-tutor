"""Unit tests never send traces, even when LANGSMITH_TRACING is on in the shell."""

from collections.abc import Iterator

import langsmith
import pytest


@pytest.fixture(autouse=True)
def _no_tracing() -> Iterator[None]:
    with langsmith.tracing_context(enabled=False):
        yield
