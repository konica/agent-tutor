"""Learner ratings as Phoenix span annotations on the ask's root span (PRD §10.2, ADR 0017), so LLM judges can be
calibrated against them. `learner_rating` is a HUMAN annotation (label up or down, score 1 or 0) whose identifier is
the run id: Phoenix upserts by name, span, and identifier, so a new rating replaces the last, and a clear deletes it by
identifier. Sent off the request on one background thread, in the order rated: a slow or unreachable Phoenix never
delays or fails the rating, which is already saved with the turn. A failure is logged. The annotation says only the
rating: no user id, email, name, or token (PRD §10.4)."""

import logging
import time
import urllib.parse
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import httpx

from smart_tutor.shared.adapters.tracing import root_span_id, tracing_enabled
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

ANNOTATION_NAME = "learner_rating"
# Phoenix drops an annotation whose span it doesn't have yet, and the agent exports the ask span a few seconds after the
# answer ends: a 404 is retried after these waits (31 s in all). Still missing then, the ask was not traced.
SPAN_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0)
REQUEST_TIMEOUT_SECONDS = 10.0


class _SpanNotTraced(Exception):
    pass


class PhoenixAnswerFeedback(AnswerFeedback):
    def __init__(
        self,
        client: httpx.Client,
        project: str,
        executor: Executor | None = None,
        waits: Sequence[float] = SPAN_WAITS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.project = project
        # One worker: requests go in the order the learner rated, so the last rating is the one left.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._waits = tuple(waits)
        self._sleep = sleep

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._submit(self._annotate, run_id, rating)

    def clear(self, run_id: RunId) -> None:
        self._submit(self._delete, run_id)

    def close(self) -> None:
        """Wait for the requests still queued (process shutdown)."""
        self._executor.shutdown(wait=True)

    def _submit(self, call: Callable[..., None], run_id: RunId, *args: object) -> None:
        self._executor.submit(call, run_id, *args).add_done_callback(lambda done: _log_failure(done, run_id))

    def _annotate(self, run_id: RunId, rating: Rating) -> None:
        body = {
            "data": [
                {
                    "span_id": f"{root_span_id(uuid.UUID(run_id)):016x}",
                    "name": ANNOTATION_NAME,
                    "annotator_kind": "HUMAN",
                    "identifier": str(run_id),
                    "result": {"label": rating.value, "score": 1 if rating is Rating.UP else 0},
                }
            ]
        }
        for wait in (*self._waits, None):
            response = self.client.post("/v1/span_annotations", params={"sync": "true"}, json=body)
            if response.status_code != 404:
                response.raise_for_status()
                return
            if wait is None:
                raise _SpanNotTraced
            self._sleep(wait)

    def _delete(self, run_id: RunId) -> None:
        response = self.client.delete(
            f"/v1/projects/{urllib.parse.quote(self.project, safe='')}/span_annotations",
            params={
                "name": ANNOTATION_NAME,
                "identifier": str(run_id),
                "annotator_kind": "HUMAN",
                "delete_all": "true",
            },
        )
        if response.status_code != 404:  # 404: the project has no trace yet, so nothing to clear
            response.raise_for_status()


def _log_failure(done: "Future[None]", run_id: RunId) -> None:
    error = done.exception()
    if error is None:
        return
    if isinstance(error, _SpanNotTraced):
        logger.warning("the rating of run %s was not sent: Phoenix has no ask span for it (not traced?)", run_id)
    elif isinstance(error, httpx.HTTPStatusError):
        logger.error("sending the rating of run %s to Phoenix failed (%s)", run_id, error.response.status_code)
    else:
        logger.error("sending the rating of run %s to Phoenix failed (%s)", run_id, type(error).__name__)


def answer_feedback(settings: Settings) -> AnswerFeedback:
    """Phoenix annotations into the agent's project while tracing is on (same URL and key as its traces); else none."""
    if not tracing_enabled(settings):
        return NoAnswerFeedback()
    key = settings.phoenix_api_key.get_secret_value()
    client = httpx.Client(
        base_url=settings.phoenix_url.rstrip("/"),
        headers={"authorization": f"Bearer {key}"} if key else None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return PhoenixAnswerFeedback(client, settings.phoenix_project)
