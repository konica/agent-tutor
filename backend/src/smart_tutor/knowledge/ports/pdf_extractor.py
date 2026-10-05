"""Reading page text out of a PDF."""

from abc import ABC, abstractmethod


class UnreadablePdfError(Exception):
    """The bytes are not a PDF we can read (corrupt, truncated, or encrypted)."""


class TooManyPagesError(Exception):
    """The PDF has more pages than the limit; raised before any text is read."""

    def __init__(self, pages: int) -> None:
        super().__init__(f"{pages} pages")
        self.pages = pages


class PdfExtractor(ABC):
    @abstractmethod
    def extract_pages(self, data: bytes, max_pages: int) -> list[str]:
        """Raw text per page (index = page number - 1; blank pages are "").

        Raises TooManyPagesError over `max_pages` (before reading text) and UnreadablePdfError.
        """
