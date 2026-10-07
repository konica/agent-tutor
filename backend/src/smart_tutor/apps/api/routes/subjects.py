"""Subject routes (subjects module): search the shared catalog for the picker's type-ahead (PRD §8 US-2b)."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query
from pydantic import BaseModel

from smart_tutor.apps.api.deps import CurrentPrincipal, SubjectChoice

router = APIRouter(tags=["subjects"])


class SubjectMatchResponse(BaseModel):
    # Only what the learner may see: no creator, no other learner's personal name (D20, D21).
    subject_id: str
    name: str
    origin: Literal["yours", "shared"]


@router.get("/subjects/search", operation_id="search_subjects")
def search_subjects(
    q: Annotated[str, Query(min_length=1, max_length=100)], principal: CurrentPrincipal, choice: SubjectChoice
) -> list[SubjectMatchResponse]:
    """The caller's subjects matching `q` (by their names), then other shared subjects (canonical names)."""
    return [
        SubjectMatchResponse(
            subject_id=m.subject_id, name=m.name, origin=cast(Literal["yours", "shared"], m.origin.value)
        )
        for m in choice.search(principal.user_id, q)
    ]
