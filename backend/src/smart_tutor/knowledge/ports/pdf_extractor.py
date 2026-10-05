"""Reading page text out of a PDF."""

from abc import ABC, abstractmethod


class UnreadablePdfError(Exception):
    """The bytes are not a PDF we can read (corrupt, truncated, or encrypted)."""


class PdfExtractor(ABC):
    @abstractmethod
    def extract_pages(self, data: bytes) -> list[str]:
        """Raw text per page (index = page number - 1; blank pages are ""); raises UnreadablePdfError."""
