import json
import logging
import threading
import time
import uuid

import httpx
import pytest
from pydantic import SecretStr

from fakes import FakePhoenix, InlineExecutor
from smart_tutor.shared.adapters.tracing import root_span_id
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.adapters.phoenix_feedback import PhoenixAnswerFeedback, answer_feedback
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import NoAnswerFeedback

RUN = RunId(str(uuid.uuid4()))
SPAN = f"{root_span_id(uuid.UUID(RUN)):016x}"
PROJECT = "smart-tutor-test"


def feedback(phoenix: FakePhoenix, waits: tuple[float, ...] = (1.0, 2.0)) -> tuple[PhoenixAnswerFeedback, list[float]]:
    slept: list[float] = []
    sender = PhoenixAnswerFeedback(
        phoenix.client(), PROJECT, executor=InlineExecutor(), waits=waits, sleep=slept.append
    )
    return sender, slept


def ratings(phoenix: FakePhoenix) -> list[tuple[str, str, str, str, float]]:
    return [
        (span, name, a["identifier"], a["result"]["label"], a["result"]["score"])
        for (span, name, _), a in phoenix.annotations.items()
    ]


def test_a_rating_is_a_human_annotation_on_the_asks_root_span() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.UP)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "up", 1)]
    [a] = phoenix.annotations.values()
    assert a["annotator_kind"] == "HUMAN"


def test_a_not_helpful_rating_scores_zero() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.DOWN)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "down", 0)]


def test_a_new_rating_replaces_the_earlier_one() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "down", 0)]


def test_clearing_deletes_only_this_runs_rating() -> None:
    other = RunId(str(uuid.uuid4()))
    other_span = f"{root_span_id(uuid.UUID(other)):016x}"
    phoenix = FakePhoenix(spans=[SPAN, other_span])
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(other, Rating.DOWN)
    sender.clear(RUN)
    assert ratings(phoenix) == [(other_span, "learner_rating", other, "down", 0)]
    [delete] = [r for r in phoenix.requests if r.method == "DELETE"]
    assert delete.url.path == f"/v1/projects/{PROJECT}/span_annotations"
    assert dict(delete.url.params) == {
        "name": "learner_rating",
        "identifier": RUN,
        "annotator_kind": "HUMAN",
        "delete_all": "true",
    }


def test_clearing_before_the_project_has_any_trace_is_nothing_to_do(caplog: pytest.LogCaptureFixture) -> None:
    phoenix = FakePhoenix(projects=())
    feedback(phoenix)[0].clear(RUN)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_rating_before_the_span_is_exported_waits_for_it() -> None:
    phoenix = FakePhoenix(late={SPAN: 2})
    sender, slept = feedback(phoenix, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "up", 1)]
    assert slept == [1.0, 2.0]


def test_a_run_that_was_never_traced_is_a_warning_after_the_last_wait(caplog: pytest.LogCaptureFixture) -> None:
    phoenix = FakePhoenix()
    sender, slept = feedback(phoenix, waits=(1.0, 2.0))
    sender.send(RUN, Rating.UP)
    assert slept == [1.0, 2.0] and phoenix.annotations == {}
    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.levelno == logging.WARNING and RUN in record.getMessage()


def test_a_failed_clear_is_logged_as_clearing(caplog: pytest.LogCaptureFixture) -> None:
    sender, _ = feedback(FakePhoenix(down=True))
    sender.clear(RUN)
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert message.startswith("clearing the rating of run")


def test_a_404_that_is_not_a_missing_span_is_an_error_and_not_retried(caplog: pytest.LogCaptureFixture) -> None:
    wrong_path = httpx.Client(
        base_url="http://phoenix.test", transport=httpx.MockTransport(lambda r: httpx.Response(404))
    )
    slept: list[float] = []
    sender = PhoenixAnswerFeedback(wrong_path, PROJECT, executor=InlineExecutor(), sleep=slept.append)
    sender.send(RUN, Rating.UP)
    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.levelno == logging.ERROR and "404" in record.getMessage() and RUN in record.getMessage()
    assert slept == []


def test_ratings_and_a_clear_apply_in_the_order_given_even_while_the_span_is_late() -> None:
    phoenix = FakePhoenix(late={SPAN: 1})
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.clear(RUN)
    assert phoenix.annotations == {}
    assert [r.method for r in phoenix.requests] == ["POST", "POST", "POST", "DELETE"]


def test_an_unreachable_phoenix_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    sender, slept = feedback(FakePhoenix(down=True))
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2 and all(RUN in m and "ConnectError" in m for m in errors)
    assert slept == []  # only a missing span is waited for


def test_a_refused_key_is_logged_with_its_status(caplog: pytest.LogCaptureFixture) -> None:
    refusing = httpx.Client(
        base_url="http://phoenix.test", transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    PhoenixAnswerFeedback(refusing, PROJECT, executor=InlineExecutor(), sleep=lambda s: None).send(RUN, Rating.UP)
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "401" in message


def test_the_annotation_carries_nothing_but_the_rating() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.DOWN)
    [post] = phoenix.requests
    assert json.loads(post.content) == {
        "data": [
            {
                "span_id": SPAN,
                "name": "learner_rating",
                "annotator_kind": "HUMAN",
                "identifier": RUN,
                "result": {"label": "down", "score": 0},
            }
        ]
    }
    assert dict(post.url.params) == {"sync": "true"}


def test_the_send_runs_off_the_callers_thread() -> None:
    release = threading.Event()
    phoenix = FakePhoenix(spans=[SPAN])

    def held(request: httpx.Request) -> httpx.Response:
        release.wait(timeout=10)
        return phoenix.transport.handle_request(request)

    client = httpx.Client(base_url="http://phoenix.test", transport=httpx.MockTransport(held))
    sender = PhoenixAnswerFeedback(client, PROJECT)
    sender.send(RUN, Rating.UP)
    assert phoenix.annotations == {}  # send returned while the request is still held back
    release.set()
    sender.close()
    assert len(phoenix.annotations) == 1


def test_close_stops_a_retry_in_progress_at_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    phoenix = FakePhoenix()
    posted = threading.Event()

    def handle(request: httpx.Request) -> httpx.Response:
        posted.set()
        return phoenix.transport.handle_request(request)

    client = httpx.Client(base_url="http://phoenix.test", transport=httpx.MockTransport(handle))
    sender = PhoenixAnswerFeedback(client, PROJECT)  # the production waits, 31 s in all
    sender.send(RUN, Rating.UP)
    assert posted.wait(timeout=5)
    time.sleep(0.1)  # the worker is now in its first wait
    started = time.monotonic()
    sender.close()
    assert time.monotonic() - started < 2
    assert len([r for r in phoenix.requests if r.method == "POST"]) == 1  # no more requests once stopping
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any(r.levelno == logging.INFO and RUN in r.getMessage() for r in caplog.records)


def test_close_cancels_ratings_not_yet_started(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    release = threading.Event()
    started = threading.Event()
    phoenix = FakePhoenix(spans=[SPAN])

    def held(request: httpx.Request) -> httpx.Response:
        started.set()
        release.wait(timeout=10)
        return phoenix.transport.handle_request(request)

    sender = PhoenixAnswerFeedback(
        httpx.Client(base_url="http://phoenix.test", transport=httpx.MockTransport(held)), PROJECT
    )
    sender.send(RUN, Rating.UP)
    assert started.wait(timeout=5)  # the first is running, held in its request
    queued = RunId(str(uuid.uuid4()))
    sender.send(queued, Rating.DOWN)
    closer = threading.Thread(target=sender.close)
    closer.start()
    time.sleep(0.1)
    release.set()
    closer.join(timeout=5)
    assert not closer.is_alive()
    assert [a["identifier"] for a in phoenix.annotations.values()] == [RUN]  # the queued one was never sent
    assert any(r.levelno == logging.INFO and queued in r.getMessage() for r in caplog.records)


def test_close_closes_the_client() -> None:
    client = FakePhoenix().client()
    PhoenixAnswerFeedback(client, PROJECT).close()
    assert client.is_closed


def test_answer_feedback_sends_to_the_agents_project_with_the_key() -> None:
    settings = Settings(
        phoenix_url="http://phoenix:6006",
        phoenix_api_key=SecretStr("k-123"),
        phoenix_project="smart-tutor-on-premise",
        deployment="on-premise",
    )
    sender = answer_feedback(settings)
    assert isinstance(sender, PhoenixAnswerFeedback)
    assert sender.project == "smart-tutor-on-premise"
    assert str(sender.client.base_url).rstrip("/") == "http://phoenix:6006"
    assert sender.client.headers["authorization"] == "Bearer k-123"
    sender.close()


def test_the_local_phoenix_needs_no_key() -> None:
    sender = answer_feedback(
        Settings(phoenix_url="http://localhost:10404", phoenix_api_key=SecretStr(""), deployment="local")
    )
    assert isinstance(sender, PhoenixAnswerFeedback) and "authorization" not in sender.client.headers
    sender.close()


@pytest.mark.parametrize(
    "settings",
    [
        Settings(phoenix_url=""),
        Settings(phoenix_url="http://phoenix:6006", phoenix_api_key=SecretStr(""), deployment="on-premise"),
    ],
    ids=["no-url", "deployed-without-key"],
)
def test_answer_feedback_is_off_while_tracing_is_off(settings: Settings) -> None:
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)
