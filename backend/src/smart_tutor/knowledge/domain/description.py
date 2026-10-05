"""What the first-pages step learns about a content, and its work key (PRD §9.2 steps 4 and 6, §9.9, D22).

The payload comes from a model reading untrusted page text, so every field is checked here and any bad field
rejects the whole payload. Error messages name the field, never its value.
"""

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from smart_tutor.knowledge.domain.errors import InvalidDescriptionError

MAX_TITLE = 500
MAX_AUTHORS = 50
MAX_AUTHOR = 200
MAX_SUMMARY = 1000
MAX_SUBJECT_NAME = 60
PROPOSED_SUBJECTS = 3
MIN_YEAR, MAX_YEAR = 1000, 2100
_DOI = re.compile(r"10\.\d{4,9}/\S+")
_DOI_PREFIX = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]")


@dataclass(frozen=True)
class DocumentDescription:
    title: str
    authors: tuple[str, ...]
    year: int | None
    doi: str | None  # normalized: lowercase, no prefix
    summary: str
    proposed_subject_names: tuple[str, ...]

    @property
    def work_key(self) -> str:
        return work_key(self.doi, self.title, self.year)


def parse_description(payload: Mapping[str, Any]) -> DocumentDescription:
    """The checked arguments of a describe_document tool call; raises InvalidDescriptionError on any bad field."""
    title = _text(payload.get("title"), "title", MAX_TITLE)
    if not normalize_title(title):
        raise InvalidDescriptionError("title has no letters or digits")
    authors = _texts(payload.get("authors"), "authors", MAX_AUTHOR)
    if len(authors) > MAX_AUTHORS:
        raise InvalidDescriptionError(f"authors has more than {MAX_AUTHORS} names")
    names = _texts(payload.get("proposed_subject_names"), "proposed_subject_names", MAX_SUBJECT_NAME)
    if len(names) != PROPOSED_SUBJECTS or len({n.casefold() for n in names}) != PROPOSED_SUBJECTS:
        raise InvalidDescriptionError(f"proposed_subject_names needs {PROPOSED_SUBJECTS} distinct names")
    return DocumentDescription(
        title=title,
        authors=tuple(authors),
        year=_year(payload.get("year")),
        doi=_doi(payload.get("doi")),
        summary=_text(payload.get("summary"), "summary", MAX_SUMMARY),
        proposed_subject_names=tuple(names),
    )


def normalize_doi(raw: str) -> str:
    """Lowercase, without a doi.org or `doi:` prefix; raises InvalidDescriptionError unless it matches 10.xxxx/yyy."""
    doi = _DOI_PREFIX.sub("", raw.strip()).lower()
    if not _DOI.fullmatch(doi):
        raise InvalidDescriptionError("doi isn't a DOI")
    return doi


def normalize_title(title: str) -> str:
    """NFKC, case-folded, letters and digits only, single spaces: equal for one title typed differently."""
    folded = unicodedata.normalize("NFKC", title).casefold()
    return " ".join("".join(ch if ch.isalnum() else " " for ch in folded).split())


def work_key(doi: str | None, title: str, year: int | None) -> str:
    """Which work a content is (PRD glossary "Work"): the DOI, else the normalized title and year."""
    if doi:
        return f"doi:{normalize_doi(doi)}"
    return f"title:{normalize_title(title)}:{'' if year is None else year}"


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise InvalidDescriptionError(f"{field} must be text")
    cleaned = " ".join(_CONTROL.sub(" ", value).split())
    if not cleaned or len(cleaned) > limit:
        raise InvalidDescriptionError(f"{field} must be 1 to {limit} characters")
    return cleaned


def _texts(value: Any, field: str, limit: int) -> list[str]:
    if not isinstance(value, list):
        raise InvalidDescriptionError(f"{field} must be a list")
    return [_text(item, field, limit) for item in value]


def _year(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not MIN_YEAR <= value <= MAX_YEAR:
        raise InvalidDescriptionError(f"year must be a whole number from {MIN_YEAR} to {MAX_YEAR}")
    return value


def _doi(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidDescriptionError("doi must be text")
    return normalize_doi(value) if value.strip() else None
