import json
import logging
import threading
import time
import uuid

import httpx
import pytest
from pydantic import SecretStr

from fakes import FakeLangfuseScores, InlineExecutor
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.adapters.langfuse_feedback import LangfuseAnswerFeedback, answer_feedback
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import NoAnswerFeedback

RUN = RunId(str(uuid.uuid4()))
TRACE = uuid.UUID(RUN).hex


def feedback(
    langfuse: FakeLangfuseScores, waits: tuple[float, ...] = (1.0, 2.0)
) -> tuple[LangfuseAnswerFeedback, list[float]]:
    slept: list[float] = []
    sender = LangfuseAnswerFeedback(
        langfuse.client(), "local", executor=InlineExecutor(), waits=waits, sleep=slept.append
    )
    return sender, slept


def values(langfuse: FakeLangfuseScores, trace: str = TRACE) -> list[bool]:
    return [s["value"] for s in langfuse.shown(trace)]


def posts(langfuse: FakeLangfuseScores) -> list[dict[str, object]]:
    return [json.loads(r.content) for r in langfuse.requests if r.method == "POST"]


def warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_rating_is_a_boolean_learner_rating_score_on_the_runs_trace() -> None:
    langfuse = FakeLangfuseScores()
    config = langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.UP)
    [body] = posts(langfuse)
    assert uuid.UUID(str(body.pop("id")))  # a new id per rating
    assert body == {
        "traceId": TRACE,
        "name": "learner_rating",
        "value": 1,
        "dataType": "BOOLEAN",
        "environment": "local",
        "configId": config,
    }
    assert values(langfuse) == [True]


def test_a_not_helpful_rating_scores_zero() -> None:
    langfuse = FakeLangfuseScores()
    langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.DOWN)
    assert [p["value"] for p in posts(langfuse)] == [0] and values(langfuse) == [False]


def test_a_rating_before_its_trace_arrives_is_sent_once_without_waiting(caplog: pytest.LogCaptureFixture) -> None:
    # Langfuse stores a score whatever its trace: the fake has no traces at all, as when the ask's trace is still
    # in the agent's export batch.
    langfuse = FakeLangfuseScores(lag=1)
    langfuse.config()
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    assert len(posts(langfuse)) == 1 and slept == [] and not warnings(caplog)


def test_a_new_rating_replaces_the_earlier_one() -> None:
    langfuse = FakeLangfuseScores()
    langfuse.config()
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert values(langfuse) == [False]
    first, second = (p["id"] for p in posts(langfuse))
    assert first != second  # never one reused id (ADR 0023 §6)


def test_a_quick_change_waits_for_the_earlier_score_to_show_before_deleting_it() -> None:
    langfuse = FakeLangfuseScores(lag=3)
    langfuse.config()
    sender, slept = feedback(langfuse, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)  # its list call: the 👍 is still queued (2 calls left)
    sender.send(RUN, Rating.DOWN)
    assert slept == [1.0]  # hidden on the first list, shown on the second
    reader = langfuse.client()
    while langfuse.hidden:  # let the 👎 finish ingesting (each list call advances the queue)
        reader.get("/api/public/v3/scores")
    assert values(langfuse) == [False]


def test_an_earlier_score_that_never_shows_is_a_warning_and_the_new_one_stays(
    caplog: pytest.LogCaptureFixture,
) -> None:
    langfuse = FakeLangfuseScores(lag=10)
    langfuse.config()
    sender, slept = feedback(langfuse, waits=(1.0, 2.0))
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert slept == [1.0, 2.0]
    [record] = warnings(caplog)
    assert record.levelno == logging.WARNING and RUN in record.getMessage()
    assert not [r for r in langfuse.requests if r.method == "DELETE"]


def test_scores_left_by_an_earlier_process_are_deleted_without_waiting_across_pages() -> None:
    langfuse = FakeLangfuseScores(page_size=2)
    langfuse.config()
    for _ in range(3):
        langfuse.seed(TRACE, value=True)
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.DOWN)
    assert values(langfuse) == [False] and slept == []


def test_clearing_deletes_only_this_runs_learner_ratings() -> None:
    other = RunId(str(uuid.uuid4()))
    langfuse = FakeLangfuseScores()
    langfuse.config()
    judge = langfuse.seed(TRACE, name="answer_relevance")
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(other, Rating.DOWN)
    sender.clear(RUN)
    assert values(langfuse) == [] and values(langfuse, uuid.UUID(other).hex) == [False]
    assert judge in langfuse.scores  # another score on the same trace stays


def test_clearing_right_after_rating_waits_for_the_rating_to_show() -> None:
    langfuse = FakeLangfuseScores(lag=2)
    langfuse.config()
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    assert langfuse.scores == {} and slept == []  # hidden for one list call, shown on the clear's first


def test_clearing_a_run_never_rated_deletes_nothing(caplog: pytest.LogCaptureFixture) -> None:
    langfuse = FakeLangfuseScores()
    sender, slept = feedback(langfuse)
    sender.clear(RUN)
    assert not [r for r in langfuse.requests if r.method == "DELETE"] and slept == [] and not warnings(caplog)


def test_the_score_config_is_looked_up_once() -> None:
    langfuse = FakeLangfuseScores()
    langfuse.config()
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert len([r for r in langfuse.requests if r.url.path == "/api/public/score-configs"]) == 1


def test_the_config_is_found_on_a_later_page() -> None:
    langfuse = FakeLangfuseScores(page_size=2)
    langfuse.config(name="answer_relevance", data_type="NUMERIC")
    langfuse.config(name="faithfulness", data_type="NUMERIC")
    config = langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.UP)
    assert posts(langfuse)[0]["configId"] == config


@pytest.mark.parametrize(
    "config",
    [None, {"data_type": "NUMERIC"}, {"archived": True}],
    ids=["missing", "not-boolean", "archived"],
)
def test_without_a_usable_config_the_score_goes_unchecked_with_one_warning(
    config: dict[str, object] | None, caplog: pytest.LogCaptureFixture
) -> None:
    langfuse = FakeLangfuseScores()
    if config is not None:
        langfuse.config(**config)  # type: ignore[arg-type]
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert ["configId" in p for p in posts(langfuse)] == [False, False]
    assert values(langfuse) == [False]
    [record] = warnings(caplog)
    assert "learner_rating" in record.getMessage() and "score config" in record.getMessage()


def test_ratings_and_a_clear_apply_in_the_order_given_even_while_scores_lag() -> None:
    langfuse = FakeLangfuseScores(lag=2)
    langfuse.config()
    sender, _ = feedback(langfuse, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.clear(RUN)
    assert langfuse.scores == {}


def test_an_unreachable_langfuse_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    sender, slept = feedback(FakeLangfuseScores(down=True))
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2 and all(RUN in m and "ConnectError" in m for m in errors)
    assert errors[1].startswith("clearing the rating of run")
    assert slept == []


def test_a_refused_key_is_logged_with_its_status(caplog: pytest.LogCaptureFixture) -> None:
    refusing = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    LangfuseAnswerFeedback(refusing, "local", executor=InlineExecutor(), sleep=lambda s: None).send(RUN, Rating.UP)
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "401" in message and RUN in message


def test_the_send_runs_off_the_callers_thread() -> None:
    release = threading.Event()
    langfuse = FakeLangfuseScores()

    def held(request: httpx.Request) -> httpx.Response:
        release.wait(timeout=10)
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(held), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")
    sender.send(RUN, Rating.UP)
    assert langfuse.scores == {}  # send returned while the request is still held back
    release.set()
    sender.close()
    assert len(langfuse.scores) == 1


def test_close_stops_a_wait_in_progress_at_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    langfuse = FakeLangfuseScores(lag=100)
    langfuse.config()
    listed = threading.Event()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/public/v3/scores" and len(langfuse.scores) == 2:
            listed.set()
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(handle), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")  # the production waits
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)  # waits for the 👍 to show, which it never does
    assert listed.wait(timeout=5)
    time.sleep(0.1)  # the worker is now in its first wait
    started = time.monotonic()
    sender.close()
    assert time.monotonic() - started < 2
    assert not warnings(caplog)
    assert any(r.levelno == logging.INFO and RUN in r.getMessage() for r in caplog.records)


def test_close_cancels_ratings_not_yet_started(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    release = threading.Event()
    started = threading.Event()
    langfuse = FakeLangfuseScores()
    langfuse.config()

    def held(request: httpx.Request) -> httpx.Response:
        started.set()
        release.wait(timeout=10)
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(held), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")
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
    assert {s["traceId"] for s in langfuse.scores.values()} <= {TRACE}  # the queued one was never sent
    assert any(r.levelno == logging.INFO and queued in r.getMessage() for r in caplog.records)


def test_close_closes_the_client() -> None:
    client = FakeLangfuseScores().client()
    LangfuseAnswerFeedback(client, "local").close()
    assert client.is_closed


def test_answer_feedback_sends_with_the_projects_key_pair_and_the_deployment() -> None:
    settings = Settings(
        langfuse_url="https://langfuse.example/",
        langfuse_public_key=SecretStr("pk-lf-1"),
        langfuse_secret_key=SecretStr("sk-lf-1"),
        deployment="on-premise",
    )
    sender = answer_feedback(settings)
    assert isinstance(sender, LangfuseAnswerFeedback)
    assert sender.environment == "on-premise"
    assert str(sender.client.base_url).rstrip("/") == "https://langfuse.example"
    request = sender.client.build_request("GET", "/api/public/v3/scores")
    request = next(sender.client.auth.auth_flow(request))
    assert request.headers["authorization"] == httpx.BasicAuth("pk-lf-1", "sk-lf-1")._auth_header
    sender.close()


@pytest.mark.parametrize(
    "settings",
    [
        Settings(langfuse_url=""),
        Settings(langfuse_url="https://langfuse.example", langfuse_public_key=SecretStr("pk")),
        Settings(langfuse_url="https://langfuse.example", langfuse_secret_key=SecretStr("sk")),
    ],
    ids=["no-url", "no-secret-key", "no-public-key"],
)
def test_answer_feedback_is_off_without_langfuse(settings: Settings) -> None:
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)


def test_phoenix_alone_sends_no_ratings() -> None:
    settings = Settings(phoenix_url="http://phoenix:6006", phoenix_api_key=SecretStr("k"), deployment="on-premise")
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)
