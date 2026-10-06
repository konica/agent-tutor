"""The shared subject catalog (PRD §9.4, D20): stable ids, canonical names, normalized names."""

import re
import unicodedata
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.errors import InvalidSubjectNameError

# Seeded by migration 0002. Documents made ready before US-2b keep it; now it is only the last-resort suggestion.
GENERAL_SUBJECT_ID = SubjectId("00000000-0000-4000-8000-000000000001")
MAX_SUBJECT_NAME = 60
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]")


@dataclass(frozen=True)
class Subject:
    subject_id: SubjectId
    canonical_name: str


def clean_subject_name(raw: str) -> str:
    """The name as shown: no control characters, single spaces, 1 to 60 characters."""
    name = " ".join(_CONTROL.sub(" ", raw).split())
    if not name or len(name) > MAX_SUBJECT_NAME:
        raise InvalidSubjectNameError(f"Subject names can be 1 to {MAX_SUBJECT_NAME} characters.")
    return name


def normalize_subject_name(name: str) -> str:
    """NFKC, case-folded, single spaces: the key of `subjects.normalized_name` (unique)."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())
