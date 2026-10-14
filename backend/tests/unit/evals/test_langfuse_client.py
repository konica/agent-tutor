"""The Langfuse seam's SDK adapter, on a stub of the SDK client: pages, archived items, experiments, and errors in our
types."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from evals.langfuse_client import KEYS, URLS, Item, LangfuseError, Score, SdkLangfuse, StoredDataset

pytest.importorskip("langfuse")  # the eval extra
import httpx  # noqa: E402
from langfuse.api import NotFoundError, UnauthorizedError  # noqa: E402


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


async def _relevance(inputs: dict[str, Any], outputs: dict[str, Any], expected: dict[str, Any]) -> list[Score]:
    return [Score("answer_relevance", 0.5 if expected["covered"] else 0.0, outputs["answer"])]


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
