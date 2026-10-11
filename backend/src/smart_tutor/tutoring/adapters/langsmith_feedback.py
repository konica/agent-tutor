"""Learner ratings as LangSmith feedback on the answer's run (PRD §10.2), so LLM judges can be calibrated against
them. Sent off the request on one background thread, in order: a slow or unreachable LangSmith never delays or fails
the rating, which is already saved with the turn. A failed send is logged. The feedback says only the rating: no user
id, email, name, or token (PRD §10.4)."""

import logging
import uuid
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import langsmith
from langsmith import utils as ls_utils

from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

FEEDBACK_KEY = "learner_rating"


class LangSmithAnswerFeedback(AnswerFeedback):
    def __init__(
        self, project_name: str, client: langsmith.Client | None = None, executor: Executor | None = None
    ) -> None:
        self._project = project_name
        self._client = client or langsmith.Client()
        # One worker: sends happen in the order the learner rated, so the last rating is the one left.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._project_id: uuid.UUID | None = None

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._executor.submit(self._replace, run_id, rating).add_done_callback(lambda done: _log_failure(done, run_id))

    def close(self) -> None:
        """Wait for the sends still queued (process shutdown)."""
        self._executor.shutdown(wait=True)

    def _replace(self, run_id: RunId, rating: Rating) -> None:
        for earlier in self._client.list_feedback(run_ids=[run_id], feedback_key=[FEEDBACK_KEY]):
            self._client.delete_feedback(earlier.id)
        self._client.create_feedback(
            run_id=run_id,
            key=FEEDBACK_KEY,
            score=1 if rating is Rating.UP else 0,
            value=rating.value,
            session_id=self._session_id(),
            # A thumbs-down keeps the trace long enough to be reviewed (PRD §10.3 item 7); a thumbs-up leaves its
            # retention as it is.
            extend_trace_retention=rating is Rating.DOWN,
        )

    def _session_id(self) -> uuid.UUID:
        if self._project_id is None:
            self._project_id = self._client.read_project(project_name=self._project).id
        return self._project_id


def _log_failure(done: "Future[None]", run_id: RunId) -> None:
    error = done.exception()
    if error is not None:
        logger.error("sending the rating of run %s to LangSmith failed (%s)", run_id, type(error).__name__)


def answer_feedback() -> AnswerFeedback:
    """LangSmith feedback while tracing is on, into the project the agent traces asks to; otherwise none."""
    if not ls_utils.tracing_is_enabled():
        return NoAnswerFeedback()
    return LangSmithAnswerFeedback(ls_utils.get_tracer_project() or "default")
