"""Citation attached to an answer: document title and page."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: str
    document_title: str
    page: int
    archived: bool = False  # archived documents still resolve; the UI marks them
