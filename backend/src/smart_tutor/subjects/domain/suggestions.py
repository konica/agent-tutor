"""Ranking 3 subject suggestions for one learner and one content (PRD §9.2 step 5, D20, US-2b)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name

SUGGESTIONS = 3
# Cosine similarity of the content summary to a subject name. Nova embeddings put related names at 0.69-0.77 and
# unrelated ones at 0.51-0.64 (measured 2026-10-06); the suggestion evals tune both values.
MATCH_THRESHOLD = 0.68
YOURS_BOOST = 0.05
_EXACT = 1.0  # a proposed name equal to an existing subject's name


class SuggestionOrigin(StrEnum):
    SHARED = "shared"
    YOURS = "yours"
    NEW = "new"


@dataclass(frozen=True)
class Suggestion:
    name: str
    origin: SuggestionOrigin
    subject_id: SubjectId | None = None  # None for a new name


@dataclass(frozen=True)
class Candidate:
    subject: Subject
    similarity: float


def rank_suggestions(
    *,
    similar: Sequence[Candidate],
    proposed_names: Sequence[str],
    existing_by_name: Mapping[str, Subject],
    yours: Mapping[SubjectId, str],
    fallback: Subject,
    threshold: float = MATCH_THRESHOLD,
    boost: float = YOURS_BOOST,
) -> list[Suggestion]:
    """Matching subjects by boosted similarity, then new proposed names, then the learner's other subjects.

    `existing_by_name` maps normalized names to subjects; `yours` maps the learner's subjects to their display
    names (a proposed name equal to one is that subject). `fallback` is used only when nothing else exists.
    """
    names = {c.subject.subject_id: c.subject.canonical_name for c in similar}
    scores: dict[SubjectId, float] = {}
    for c in similar:
        score = c.similarity + (boost if c.subject.subject_id in yours else 0.0)
        if score >= threshold:
            scores[c.subject.subject_id] = max(score, scores.get(c.subject.subject_id, score))
    yours_by_name = {normalize_subject_name(name): sid for sid, name in yours.items()}
    new_names: list[str] = []
    for proposed in proposed_names:
        key = normalize_subject_name(proposed)
        existing = existing_by_name.get(key)
        sid = yours_by_name.get(key) or (existing.subject_id if existing else None)
        if sid is None:
            if key not in {normalize_subject_name(n) for n in new_names}:
                new_names.append(proposed)
            continue
        if existing is not None:
            names.setdefault(sid, existing.canonical_name)
        scores[sid] = max(scores.get(sid, 0.0), _EXACT + (boost if sid in yours else 0.0))

    def suggestion(sid: SubjectId, fallback_name: str) -> Suggestion:
        origin = SuggestionOrigin.YOURS if sid in yours else SuggestionOrigin.SHARED
        return Suggestion(yours.get(sid, fallback_name), origin, sid)

    ranked = sorted(scores, key=lambda sid: (-scores[sid], yours.get(sid, names.get(sid, ""))))
    result = [suggestion(sid, names.get(sid, "")) for sid in ranked[:SUGGESTIONS]]
    result += [Suggestion(name, SuggestionOrigin.NEW) for name in new_names]
    chosen = {s.subject_id for s in result}
    result += [suggestion(sid, name) for sid, name in sorted(yours.items(), key=lambda p: p[1]) if sid not in chosen]
    if not result:
        result = [suggestion(fallback.subject_id, fallback.canonical_name)]
    return result[:SUGGESTIONS]
