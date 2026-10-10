"""Module-level (picklable) extractors for TimeLimitedExtractor tests: the spawn child imports them by name."""

import os
import time

from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor, TooManyPagesError, UnreadablePdfError


class PagesExtractor(PdfExtractor):
    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        return [data.decode(), "second"]


class TooManyExtractor(PdfExtractor):
    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        raise TooManyPagesError(600)


class UnreadableExtractor(PdfExtractor):
    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        raise UnreadablePdfError("bad bytes")


class SleepingExtractor(PdfExtractor):
    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        time.sleep(60)
        return []


class CrashingExtractor(PdfExtractor):
    def extract_pages(self, data: bytes, max_pages: int, first: int | None = None) -> list[str]:
        os._exit(137)
