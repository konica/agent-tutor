"""Citation attached to an answer: document title and page, and the [n] marker that points at it."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Citation:
    chunk_id: str
    document_title: str
    page: int | None  # None renders "page unavailable"
    archived: bool = False  # archived documents still resolve; the UI marks them
    n: int | None = None  # the answer's [n] marker for this citation (its chunk's place in the prompt)
    document_id: str | None = None  # the cited document, where the citation came from search
