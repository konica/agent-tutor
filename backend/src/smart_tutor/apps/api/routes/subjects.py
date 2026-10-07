"""Subject routes: my subjects, the subjects of the learner's ready documents (PRD §4, §8 US-3), and search of the
shared catalog for the picker's type-ahead (PRD §8 US-2b)."""

from typing import Annotated, Literal, cast

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, SubjectChoice, Subjects
from smart_tutor.apps.api.routes.knowledge import SubjectResponse

router = APIRouter(tags=["subjects"])

UNNAMED_SUBJECT = "Unnamed subject"  # the agent refuses an empty name


class SubjectMatchResponse(BaseModel):
    # Only what the learner may see: no creator, no other learner's personal name (D20, D21).
    subject_id: str
    name: str
    origin: Literal["yours", "shared"]


@router.get("/me/subjects", operation_id="list_my_subjects")
async def list_my_subjects(
    principal: CurrentPrincipal, documents: Documents, subjects: Subjects
) -> list[SubjectResponse]:
    mine = await run_in_threadpool(documents.learner_subjects, principal.user_id)
    names = await run_in_threadpool(subjects.names_for, principal.user_id, mine)
    listed = [SubjectResponse(subject_id=s, name=names.get(s) or UNNAMED_SUBJECT) for s in mine]
    return sorted(listed, key=lambda r: (r.name.casefold(), r.subject_id))


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
