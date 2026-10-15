"""The Langfuse seam's SDK adapter, on a stub of the SDK client: pages, archived items, review queues, experiments,
and errors in our types."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from evals.langfuse_client import KEYS, URLS, Item, ItemScore, LangfuseError, Score, SdkLangfuse, StoredDataset, Trace

pytest.importorskip("langfuse")  # the eval extra
import httpx  # noqa: E402
from langfuse.api import (  # noqa: E402
    AnnotationQueueObjectType,
    NotFoundError,
    ScoreConfigDataType,
    ScoreDataType,
    UnauthorizedError,
)


def _page(names: list[str], total_pages: int) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(name=n) for n in names], meta=SimpleNamespace(total_pages=total_pages))


class StubSdk:
    def __init__(self, pages: list[list[str]] | None = None, error: Exception | None = None) -> None:
        self.pages, self.error = pages or [[]], error
        self.created: list[dict[str, Any]] = []
        self.experiments: list[dict[str, Any]] = []
        self.run_url: str | None = "https://langfuse.example/project/p/datasets/d/runs/r"
        self.api = SimpleNamespace(datasets=SimpleNamespace(list=self._list))

    def _list(self, *, page: int, limit: int) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        return _page(self.pages[page - 1], len(self.pages))

    def get_dataset(self, name: str) -> SimpleNamespace:
        if self.error is not None:
            raise self.error
        active = SimpleNamespace(
            input={"question": "q"}, expected_output={"covered": True}, metadata=None, status="ACTIVE"
        )
        archived = SimpleNamespace(input={"question": "x"}, expected_output=None, metadata=None, status="ARCHIVED")
        return SimpleNamespace(name=name, metadata={"examples": 1}, items=[active, archived])

    def create_dataset(self, **kwargs: Any) -> None:
        self.created.append({"dataset": kwargs})

    def create_dataset_item(self, **kwargs: Any) -> None:
        self.created.append({"item": kwargs})

    def run_experiment(self, **kwargs: Any) -> SimpleNamespace:
        """As the SDK calls a task and evaluators: keyword arguments, with each item's metadata."""

        async def one(item: Any) -> dict[str, Any]:
            output = await kwargs["task"](item=item)
            evaluations = []
            for evaluator in kwargs["evaluators"]:
                given = {"input": item.input, "output": output, "expected_output": item.expected_output}
                evaluations += await evaluator(**given, metadata=item.metadata)
            return {"output": output, "evaluations": evaluations}

        async def every() -> list[dict[str, Any]]:
            return [await one(item) for item in kwargs["data"]]

        self.experiments.append({**kwargs, "results": asyncio.run(every())})
        return SimpleNamespace(dataset_run_url=self.run_url)


def test_dataset_names_reads_every_page() -> None:
    assert SdkLangfuse(StubSdk([["a/smoke-v1", "a/full-v1"], ["b/full-v1"]])).dataset_names() == [
        "a/smoke-v1",
        "a/full-v1",
        "b/full-v1",
    ]


def test_a_dataset_comes_back_with_its_active_items_only() -> None:
    assert SdkLangfuse(StubSdk()).get_dataset("a/smoke-v1") == StoredDataset(
        "a/smoke-v1", {"examples": 1}, (Item({"question": "q"}, {"covered": True}, {}),)
    )


def test_a_missing_dataset_is_none() -> None:
    stub = StubSdk(error=NotFoundError(body="Dataset not found"))
    assert SdkLangfuse(stub).get_dataset("a/smoke-v9") is None


def test_items_are_created_with_their_reference_outputs_and_metadata() -> None:
    stub = StubSdk()
    client = SdkLangfuse(stub)
    client.create_dataset("a/smoke-v1", description="d", metadata={"split": "smoke", "examples": 1})
    client.create_item("a/smoke-v1", Item({"question": "q"}, {"covered": True}, {"type": "factual"}))
    client.create_item("a/smoke-v1", Item({"question": "h"}, {}))
    assert stub.created == [
        {"dataset": {"name": "a/smoke-v1", "description": "d", "metadata": {"split": "smoke", "examples": 1}}},
        {
            "item": {
                "dataset_name": "a/smoke-v1",
                "input": {"question": "q"},
                "expected_output": {"covered": True},
                "metadata": {"type": "factual"},
            }
        },
        {"item": {"dataset_name": "a/smoke-v1", "input": {"question": "h"}, "expected_output": {}, "metadata": None}},
    ]


async def _answer(inputs: dict[str, Any]) -> dict[str, Any]:
    return {"answer": f"about {inputs['question']}"}


async def _relevance(inputs: dict[str, Any], outputs: dict[str, Any], expected: dict[str, Any]) -> list[ItemScore]:
    return [ItemScore("answer_relevance", 0.5 if expected["covered"] else 0.0, outputs["answer"])]


def _run(client: SdkLangfuse) -> str:
    return client.run_experiment(
        "a/smoke-v1",
        run_name="local 2026-10-14 09:00:00Z",
        description="smoke evals on smoke-v1",
        metadata={"split": "smoke"},
        task=_answer,
        evaluators=[_relevance],
        max_concurrency=4,
    )


def test_an_experiment_runs_the_active_items_as_a_dataset_run_with_numeric_scores() -> None:
    stub = StubSdk()
    assert _run(SdkLangfuse(stub)) == "https://langfuse.example/project/p/datasets/d/runs/r"
    [experiment] = stub.experiments
    assert experiment["name"] == "a/smoke-v1" and experiment["run_name"] == "local 2026-10-14 09:00:00Z"
    assert experiment["description"] == "smoke evals on smoke-v1" and experiment["metadata"] == {"split": "smoke"}
    assert experiment["max_concurrency"] == 4
    assert [i.input for i in experiment["data"]] == [{"question": "q"}]  # the archived item stays out
    [result] = experiment["results"]
    assert result["output"] == {"answer": "about q"}
    [evaluation] = result["evaluations"]
    assert (evaluation.name, evaluation.value, evaluation.comment) == ("answer_relevance", 0.5, "about q")
    assert evaluation.data_type == "NUMERIC"
    assert experiment["evaluators"][0].__name__ == "_relevance"  # the evaluator's observation in Langfuse


def test_an_experiment_without_a_run_link_is_named_by_its_run() -> None:
    stub = StubSdk()
    stub.run_url = None
    assert _run(SdkLangfuse(stub)) == "local 2026-10-14 09:00:00Z"


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (UnauthorizedError(body="Invalid credentials"), "401: Invalid credentials"),
        (httpx.ConnectError("Connection refused"), "Connection refused"),
    ],
)
def test_langfuse_and_network_failures_are_langfuse_errors(error: Exception, says: str) -> None:
    with pytest.raises(LangfuseError, match=says):
        SdkLangfuse(StubSdk(error=error)).dataset_names()


def test_missing_keys_or_url_are_named_before_any_call(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (*KEYS, *URLS):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(LangfuseError, match="LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY not set"):
        SdkLangfuse()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    with pytest.raises(LangfuseError, match="LANGFUSE_BASE_URL not set"):
        SdkLangfuse()


def test_the_runtime_url_setting_is_the_fallback_and_tracing_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setenv("SMART_TUTOR_LANGFUSE_URL", "https://langfuse.example")
    made: dict[str, Any] = {}
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: made.update(kwargs) or StubSdk())
    SdkLangfuse()
    assert made == {"base_url": "https://langfuse.example", "tracing_enabled": False}


def test_an_experiment_client_traces(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example")
    made: dict[str, Any] = {}
    monkeypatch.setattr("langfuse.Langfuse", lambda **kwargs: made.update(kwargs) or StubSdk())
    SdkLangfuse(tracing=True)
    assert made == {"base_url": "https://langfuse.example", "tracing_enabled": True}


class StubApi:
    """The SDK's REST resources the review queue uses, recording each call."""

    def __init__(self, ingestion_errors: list[SimpleNamespace] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ingestion_errors = ingestion_errors or []
        self.score_configs = SimpleNamespace(get=self._configs, create=self._record("create_config", id="c-new"))
        self.annotation_queues = SimpleNamespace(
            list_queues=self._queues,
            create_queue=self._record("create_queue", id="q-new"),
            create_queue_item=self._queue_item,
        )
        self.ingestion = SimpleNamespace(batch=self._batch)
        self.trace = SimpleNamespace(list=self._traces)
        self.scores = SimpleNamespace(get_many=self._scores)

    def _record(self, name: str, **returned: Any) -> Any:
        def call(**kwargs: Any) -> SimpleNamespace:
            self.calls.append((name, kwargs))
            return SimpleNamespace(**returned)

        return call

    @staticmethod
    def _paged(rows: list[list[SimpleNamespace]], page: int) -> SimpleNamespace:
        return SimpleNamespace(data=rows[page - 1], meta=SimpleNamespace(total_pages=len(rows)))

    def _configs(self, *, page: int, limit: int) -> SimpleNamespace:
        archived = SimpleNamespace(id="c-old", name="accepted", is_archived=True)
        other = SimpleNamespace(id="c-1", name="note", is_archived=False)
        live = SimpleNamespace(id="c-2", name="accepted", is_archived=False)
        return self._paged([[archived, other], [live]], page)

    def _queues(self, *, page: int, limit: int) -> SimpleNamespace:
        return self._paged([[SimpleNamespace(id="q-1", name="a-candidates")], []], page)

    def _queue_item(self, queue_id: str, **kwargs: Any) -> None:
        self.calls.append(("queue_item", {"queue_id": queue_id, **kwargs}))

    def _batch(self, *, batch: list[Any]) -> SimpleNamespace:
        self.calls.append(("batch", {"batch": batch}))
        return SimpleNamespace(successes=[], errors=self.ingestion_errors)

    def _traces(self, *, page: int, limit: int, **filters: Any) -> SimpleNamespace:
        self.calls.append(("traces", filters))
        trace = SimpleNamespace(
            id="ab" * 16,
            name="a-candidates",
            input={"question": "q"},
            output={"type": "factual"},
            metadata=None,
            timestamp=datetime(2026, 10, 14, 1, 2, 3),  # naive, read as UTC
            environment="local",
        )
        return self._paged([[trace]], page)

    def _scores(self, *, page: int, limit: int, **filters: Any) -> SimpleNamespace:
        self.calls.append(("scores", filters))
        at = datetime(2026, 10, 14, tzinfo=UTC)
        edited = datetime(2026, 10, 15, tzinfo=UTC)  # a reviewer changed it a day later
        on_trace = SimpleNamespace(trace_id="ab" * 16, name="accepted", value=1.0, timestamp=at, updated_at=edited)
        on_session = SimpleNamespace(trace_id=None, name="accepted", value=0.0, timestamp=at, updated_at=at)
        return self._paged([[on_trace, on_session]], page)


def _sdk(api: StubApi) -> SdkLangfuse:
    return SdkLangfuse(SimpleNamespace(api=api))


def test_the_score_config_is_the_unarchived_one_of_that_name_on_any_page() -> None:
    client = _sdk(StubApi())
    assert client.score_config_id("accepted") == "c-2"
    assert client.score_config_id("missing") is None


def test_a_boolean_score_config_and_a_queue_on_it_are_created() -> None:
    api = StubApi()
    client = _sdk(api)
    assert client.create_boolean_score_config("accepted", description="d") == "c-new"
    assert client.create_queue("a-candidates", description="rubric", score_config_id="c-new") == "q-new"
    assert api.calls == [
        ("create_config", {"name": "accepted", "data_type": ScoreConfigDataType.BOOLEAN, "description": "d"}),
        ("create_queue", {"name": "a-candidates", "description": "rubric", "score_config_ids": ["c-new"]}),
    ]


def test_a_queue_is_found_by_name() -> None:
    client = _sdk(StubApi())
    assert client.queue_id("a-candidates") == "q-1"
    assert client.queue_id("b-candidates") is None


def _trace(i: int) -> Trace:
    at = datetime(2026, 10, 14, tzinfo=UTC)
    return Trace(f"{i:032x}", "a-candidates", {"question": f"q{i}"}, {"type": "factual"}, {"batch": "b"}, at, "local")


def test_traces_are_sent_as_trace_create_events_in_batches_of_50() -> None:
    api = StubApi()
    _sdk(api).create_traces([_trace(i) for i in range(60)])
    batches = [kwargs["batch"] for name, kwargs in api.calls if name == "batch"]
    assert [len(b) for b in batches] == [50, 10]
    event = batches[1][0].model_dump(by_alias=True, exclude_none=True)
    assert event["type"] == "trace-create"
    assert event["body"] == {
        "id": f"{50:032x}",
        "name": "a-candidates",
        "input": {"question": "q50"},
        "output": {"type": "factual"},
        "metadata": {"batch": "b"},
        "timestamp": datetime(2026, 10, 14, tzinfo=UTC),
        "environment": "local",
    }


def test_a_trace_ingestion_refused_is_a_langfuse_error() -> None:
    api = StubApi([SimpleNamespace(id="e1", status=400, message="Invalid request data", error=None)])
    with pytest.raises(LangfuseError, match="1 of 1 traces refused, first 400: Invalid request data"):
        _sdk(api).create_traces([_trace(1)])


def test_a_trace_is_queued_as_a_trace_item() -> None:
    api = StubApi()
    _sdk(api).queue_trace("q-1", "ab" * 16)
    assert api.calls == [
        ("queue_item", {"queue_id": "q-1", "object_id": "ab" * 16, "object_type": AnnotationQueueObjectType.TRACE})
    ]


def test_traces_of_a_name_come_back_with_their_input_output_and_a_utc_timestamp() -> None:
    api = StubApi()
    [trace] = _sdk(api).traces("a-candidates")
    when = datetime(2026, 10, 14, 1, 2, 3, tzinfo=UTC)
    assert trace == Trace("ab" * 16, "a-candidates", {"question": "q"}, {"type": "factual"}, {}, when, "local")
    assert api.calls == [("traces", {"name": "a-candidates", "fields": "core,io"})]


def test_boolean_scores_are_read_by_name_with_when_they_were_last_set_and_only_trace_scores_count() -> None:
    api = StubApi()
    edited = datetime(2026, 10, 15, tzinfo=UTC)
    assert _sdk(api).boolean_scores("accepted") == [Score("ab" * 16, "accepted", 1.0, edited)]
    assert api.calls == [("scores", {"name": "accepted", "data_type": ScoreDataType.BOOLEAN})]
