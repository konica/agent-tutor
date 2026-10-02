"""EmbeddingModel port (PRD §9.15)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence


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
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed chunks for indexing (Nova: GENERIC_INDEX)."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query (Nova: TEXT_RETRIEVAL)."""
