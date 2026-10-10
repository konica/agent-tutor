"""Quality monitoring (insights): a content-free count of citation highlights the viewer couldn't draw (PRD §10.1)."""

from fastapi import APIRouter, Response

from smart_tutor.apps.api.deps import HighlightMisses

router = APIRouter(tags=["insights"])


@router.post("/viewer/highlight-misses", operation_id="record_highlight_miss", status_code=204)
def record_highlight_miss(misses: HighlightMisses) -> Response:
    """Add one to today's count. Takes no body and stores nothing about the caller: the route needs a signed-in
    learner only to keep the endpoint from being open to the internet."""
    misses.record()
    return Response(status_code=204)
