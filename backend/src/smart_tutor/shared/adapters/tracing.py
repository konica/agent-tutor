"""LangSmith tracing (PRD §10.4): who a run is for appears only as a keyed hash of the learner's user id, so usage can
be grouped per learner without the trace naming them. Tokens, user ids, and emails never reach a trace (ADR 0007)."""

import hashlib
import hmac
import logging
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager

import langsmith
from langsmith import run_trees
from langsmith import utils as ls_utils

from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing

KEY_SETTING = "SMART_TUTOR_LEARNER_HASH_KEY"

logger = logging.getLogger(__name__)


@contextmanager
def never_raising[T](cm: AbstractContextManager[T], fallback: T) -> Iterator[T]:
    """Runs the block inside `cm`, a trace, but a trace that can't start or end is logged and skipped: tracing never
    fails the work it traces (#229). The block's own errors still propagate."""
    try:
        value = cm.__enter__()
    except Exception:
        logger.warning("tracing could not start; running untraced", exc_info=True)
        yield fallback
        return
    try:
        yield value
    except BaseException as error:
        try:
            cm.__exit__(type(error), error, error.__traceback__)
        except Exception:
            logger.warning("tracing could not end", exc_info=True)
        raise
    try:
        cm.__exit__(None, None, None)
    except Exception:
        logger.warning("tracing could not end", exc_info=True)


class LearnerHasher:
    """HMAC-SHA256 of a user id: stable per learner and key, different between learners, changed with the key."""

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError(f"{KEY_SETTING} is empty")
        self._key = key.encode()

    def __call__(self, user_id: UserId) -> str:
        return hmac.new(self._key, user_id.encode(), hashlib.sha256).hexdigest()


def learner_hasher(settings: Settings) -> LearnerHasher | None:
    """The configured hasher; None when no key is set and tracing is off. Refuses to start without a key while
    tracing is on, so a trace never goes out without its learner hash."""
    key = settings.learner_hash_key.get_secret_value()
    if key:
        return LearnerHasher(key)
    if ls_utils.tracing_is_enabled():
        raise RuntimeError(f"{KEY_SETTING} is not set, but LangSmith tracing is on")
    return None


def start_tracing(settings: Settings) -> LearnerHasher | None:
    """Startup check for a process that traces: the learner-hash key (see `learner_hasher`), and, while tracing is
    on, LangSmith's own settings, by building the default client now. A sampling rate outside 0–1 then stops startup
    instead of failing every trace."""
    hasher = learner_hasher(settings)
    if ls_utils.tracing_is_enabled():
        run_trees.get_cached_client()
    return hasher


def run_metadata(settings: Settings) -> dict[str, str]:
    """What every traced run says about where it ran and with which models."""
    return {
        "deployment": settings.deployment,
        "chat_model": settings.models.agent.model_id,
        "embedding_model": settings.models.embedding.model_id,
    }


def ingestion_project() -> str:
    """The worker's own project, beside the ask project, so ask traces stay readable."""
    return f"{ls_utils.get_tracer_project()}-ingestion"


class LangSmithRunTracing(RunTracing):
    def __init__(
        self,
        hasher: LearnerHasher | None,
        project_name: str,
        metadata: Mapping[str, str],
        client: langsmith.Client | None = None,
    ) -> None:
        self._hasher = hasher
        self._project = project_name
        self._metadata = dict(metadata)
        self._client = client  # None: LangSmith's default client; tests pass a recording one

    @contextmanager
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> Iterator[None]:
        learner = {"learner_hash": self._hasher(user_id)} if self._hasher else {}
        trace = langsmith.trace(
            name, project_name=self._project, metadata={**self._metadata, **metadata, **learner}, client=self._client
        )
        with never_raising(trace, None):
            yield
