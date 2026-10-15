"""Learner ratings as Langfuse scores on the ask's trace (PRD §10.2, ADR 0023 §6), so LLM judges can be calibrated
against them. Each rating is a new `learner_rating` BOOLEAN score (1 up, 0 down) on the trace whose id is the run id,
with the deployment as its environment and, when the project has one, the `learner_rating` score config's id (Langfuse
checks a score against a config only by id). Then the trace's other `learner_rating` scores are deleted, so the new one
replaces them; clearing deletes them all. Langfuse stores a score whatever its trace, so a rating that arrives before
the ask's trace is simply sent. But it ingests a score a few seconds after answering, and a delete that arrives first
removes nothing: so before deleting, the adapter waits until the list shows the score this process last posted for
the run. Sent off the request on one background thread, in the order rated: a slow or unreachable Langfuse never
delays or fails the rating, which is already saved with the turn. A failure is logged. `close()` (API shutdown) stops
the waits and drops the requests not yet started. The score says only the rating: no user id, email, name, or token
(PRD §10.4)."""

import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any

import httpx

from smart_tutor.shared.adapters.tracing import langfuse_enabled
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

SCORE_NAME = "learner_rating"
SCORES_PATH = "/api/public/scores"
# The list that works on a v4 host in events_only mode; the v1 and v2 lists answer 404 there.
SCORES_LIST_PATH = "/api/public/v3/scores"
SCORE_CONFIGS_PATH = "/api/public/score-configs"
PAGE_LIMIT = 100  # the most either list returns per page
# Langfuse ingests a score 5 s (15 s around 00:00 UTC) after its POST, plus processing. Before deleting the score this
# process last posted for a run, wait for it to show, after these waits (61 s in all).
SHOW_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
REQUEST_TIMEOUT_SECONDS = 10.0
REMEMBERED_RUNS = 1024  # runs whose last score id is kept; older ones have long been ingested


class _Stopped(Exception):
    """The adapter is closing: a wait gives up without another request."""


class LangfuseAnswerFeedback(AnswerFeedback):
    def __init__(
        self,
        client: httpx.Client,
        environment: str,
        executor: Executor | None = None,
        waits: Sequence[float] = SHOW_WAITS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.client = client
        self.environment = environment
        # One worker: requests go in the order the learner rated, so the last rating is the one left. Only it touches
        # the state below.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._waits = tuple(waits)
        self._stopping = threading.Event()
        self._sleep = sleep or self._stopping.wait  # an injected sleep is for tests; this one wakes at close()
        self._posted: OrderedDict[RunId, str] = OrderedDict()  # run -> the score id this process last posted
        self._config_id: str | None = None
        self._warned_no_config = False

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._submit("sending", self._score, run_id, rating)

    def clear(self, run_id: RunId) -> None:
        self._submit("clearing", self._clear, run_id)

    def close(self) -> None:
        """Process shutdown: stop the wait in progress, drop the requests not yet started, close the client."""
        self._stopping.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.client.close()

    def _submit(self, action: str, call: Callable[..., None], run_id: RunId, *args: object) -> None:
        self._executor.submit(call, run_id, *args).add_done_callback(lambda done: _log_failure(done, action, run_id))

    def _score(self, run_id: RunId, rating: Rating) -> None:
        earlier = self._posted.pop(run_id, None)
        score_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "id": score_id,
            "traceId": uuid.UUID(run_id).hex,
            "name": SCORE_NAME,
            "value": 1 if rating is Rating.UP else 0,
            "dataType": "BOOLEAN",
            "environment": self.environment,
        }
        if config_id := self._config():
            body["configId"] = config_id
        self.client.post(SCORES_PATH, json=body).raise_for_status()
        self._posted[run_id] = score_id
        while len(self._posted) > REMEMBERED_RUNS:
            self._posted.popitem(last=False)
        self._delete_others(run_id, keep=score_id, earlier=earlier)

    def _clear(self, run_id: RunId) -> None:
        self._delete_others(run_id, keep=None, earlier=self._posted.pop(run_id, None))

    def _delete_others(self, run_id: RunId, keep: str | None, earlier: str | None) -> None:
        """Delete the trace's learner_rating scores but `keep`, once `earlier` (the score this process last posted for
        the run, still maybe queued) shows; a delete sent before it shows would be lost."""
        for wait in (*self._waits, None):
            if self._stopping.is_set():
                raise _Stopped
            shown = self._score_ids(run_id)
            if earlier is None or earlier in shown:
                break
            if wait is None:
                logger.warning(
                    "the earlier rating of run %s never showed in Langfuse; it may stay beside the new one", run_id
                )
                break
            self._sleep(wait)
        for score_id in shown - {keep}:
            self.client.delete(f"{SCORES_PATH}/{score_id}").raise_for_status()

    def _score_ids(self, run_id: RunId) -> set[str]:
        params = {"traceId": uuid.UUID(run_id).hex, "name": SCORE_NAME, "limit": str(PAGE_LIMIT)}
        ids: set[str] = set()
        while True:
            response = self.client.get(SCORES_LIST_PATH, params=params)
            response.raise_for_status()
            page = response.json()
            ids |= {score["id"] for score in page["data"]}
            cursor = page.get("meta", {}).get("cursor")
            if not cursor:
                return ids
            params["cursor"] = cursor

    def _config(self) -> str | None:
        """The project's learner_rating BOOLEAN config, looked up until found; None (and one warning) without it."""
        if self._config_id is None:
            page = 1
            while True:
                response = self.client.get(SCORE_CONFIGS_PATH, params={"page": page, "limit": PAGE_LIMIT})
                response.raise_for_status()
                found = response.json()
                for config in found["data"]:
                    if config["name"] == SCORE_NAME and config["dataType"] == "BOOLEAN" and not config["isArchived"]:
                        self._config_id = config["id"]
                        return self._config_id
                if page >= found["meta"]["totalPages"]:
                    break
                page += 1
            if not self._warned_no_config:
                self._warned_no_config = True
                logger.warning(
                    "the Langfuse project has no %s BOOLEAN score config; ratings are sent unchecked", SCORE_NAME
                )
        return self._config_id


def _log_failure(done: "Future[None]", action: str, run_id: RunId) -> None:
    if done.cancelled():
        logger.info("the rating of run %s was not sent: the API is stopping", run_id)
        return
    error = done.exception()
    if error is None:
        return
    if isinstance(error, _Stopped):
        logger.info("the rating of run %s was not sent: the API is stopping", run_id)
    elif isinstance(error, httpx.HTTPStatusError):
        logger.error("%s the rating of run %s to Langfuse failed (%s)", action, run_id, error.response.status_code)
    else:
        logger.error("%s the rating of run %s to Langfuse failed (%s)", action, run_id, type(error).__name__)


def answer_feedback(settings: Settings) -> AnswerFeedback:
    """Scores into the environment's Langfuse project while Langfuse tracing is on (same URL and key pair as its
    traces); else none."""
    if not langfuse_enabled(settings):
        return NoAnswerFeedback()
    client = httpx.Client(
        base_url=settings.langfuse_url.rstrip("/"),
        auth=(settings.langfuse_public_key.get_secret_value(), settings.langfuse_secret_key.get_secret_value()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return LangfuseAnswerFeedback(client, settings.deployment)
