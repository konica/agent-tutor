import logging
import threading
import uuid
from typing import Any

import pytest

from fakes import FeedbackClient, InlineExecutor
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.adapters.langsmith_feedback import LangSmithAnswerFeedback, answer_feedback
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import NoAnswerFeedback

RUN = RunId(str(uuid.uuid4()))


def feedback(client: FeedbackClient) -> LangSmithAnswerFeedback:
    return LangSmithAnswerFeedback("smart-tutor-test", client=client, executor=InlineExecutor())


def test_a_helpful_rating_is_feedback_on_the_run_without_extending_retention() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.UP)
    [f] = client.feedback.values()
    assert str(f["run_id"]) == RUN and f["key"] == "learner_rating"
    assert f["score"] == 1 and f["value"] == "up"
    assert f["session_id"] == client.project_id
    assert f["extend_trace_retention"] is False


def test_a_not_helpful_rating_extends_the_traces_retention() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.DOWN)
    [f] = client.feedback.values()
    assert f["score"] == 0 and f["value"] == "down" and f["extend_trace_retention"] is True


def test_a_new_rating_replaces_the_runs_earlier_one() -> None:
    client = FeedbackClient()
    sender = feedback(client)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.send(RUN, Rating.UP)
    [f] = client.feedback.values()
    assert f["value"] == "up"


def test_another_runs_feedback_is_left_alone() -> None:
    client = FeedbackClient()
    other = RunId(str(uuid.uuid4()))
    sender = feedback(client)
    sender.send(other, Rating.DOWN)
    sender.send(RUN, Rating.UP)
    assert sorted(f["value"] for f in client.feedback.values()) == ["down", "up"]


def test_the_feedback_carries_nothing_but_the_rating() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.DOWN)
    [(_, created)] = [c for c in client.calls if c[0] == "create_feedback"]
    assert set(created) == {"run_id", "key", "score", "value", "session_id", "extend_trace_retention"}


def test_the_project_is_read_once() -> None:
    client = FeedbackClient()
    sender = feedback(client)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    reads = [kwargs for name, kwargs in client.calls if name == "read_project"]
    assert reads == [{"project_name": "smart-tutor-test"}]


def test_an_unreachable_langsmith_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    client = FeedbackClient(fail=ConnectionError("down"))
    feedback(client).send(RUN, Rating.UP)
    assert any(r.levelno == logging.ERROR and "ConnectionError" in r.getMessage() for r in caplog.records)


def test_the_send_runs_off_the_callers_thread() -> None:
    release = threading.Event()

    class BlockedClient(FeedbackClient):
        def create_feedback(self, run_id: Any = None, key: str = "unnamed", **kwargs: Any) -> Any:
            release.wait(timeout=10)
            return super().create_feedback(run_id, key, **kwargs)

    client = BlockedClient()
    sender = LangSmithAnswerFeedback("smart-tutor-test", client=client)
    sender.send(RUN, Rating.UP)
    assert client.feedback == {}  # send returned while the feedback is still held back
    release.set()
    sender.close()
    assert len(client.feedback) == 1


def test_answer_feedback_is_off_while_tracing_is_off() -> None:
    assert isinstance(answer_feedback(), NoAnswerFeedback)
