"""EmbeddingModel port (PRD §9.15)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

from smart_tutor.shared.domain.token_usage import TokenUsage


@dataclass(frozen=True, slots=True)
class Embeddings:
    """Vectors in input order, and the tokens spent (counted as input; embeddings have no output tokens)."""

    vectors: list[list[float]]
    usage: TokenUsage


class EmbeddingModel(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Recorded on every chunk as `embedding_model`."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Recorded on every chunk as `embedding_dim`."""

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> Embeddings:
        """Embed chunks, summaries, and subject names for indexing (Nova: GENERIC_INDEX)."""

    @abstractmethod
    async def embed_query(self, text: str) -> Embeddings:
        """Embed one search query (Nova: TEXT_RETRIEVAL); `vectors` has one entry."""
