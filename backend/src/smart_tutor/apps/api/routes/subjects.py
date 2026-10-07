"""Subject routes: my subjects, the subjects of the learner's ready documents (PRD §4, §8 US-3)."""

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, Subjects
from smart_tutor.apps.api.routes.knowledge import SubjectResponse

router = APIRouter(tags=["subjects"])

UNNAMED_SUBJECT = "Unnamed subject"  # the agent refuses an empty name


@router.get("/me/subjects", operation_id="list_my_subjects")
async def list_my_subjects(
    principal: CurrentPrincipal, documents: Documents, subjects: Subjects
) -> list[SubjectResponse]:
    mine = await run_in_threadpool(documents.learner_subjects, principal.user_id)
    names = await run_in_threadpool(subjects.names_for, principal.user_id, mine)
    listed = [SubjectResponse(subject_id=s, name=names.get(s) or UNNAMED_SUBJECT) for s in mine]
    return sorted(listed, key=lambda r: (r.name.casefold(), r.subject_id))
