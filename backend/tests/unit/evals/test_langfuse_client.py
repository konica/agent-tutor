"""The Langfuse seam's SDK adapter, on a stub of the SDK client: pages, archived items, and errors in our types."""

from types import SimpleNamespace
from typing import Any

import pytest

from evals.langfuse_client import KEYS, URLS, Item, LangfuseError, SdkLangfuse, StoredDataset

pytest.importorskip("langfuse")  # the eval extra
import httpx  # noqa: E402
from langfuse.api import NotFoundError, UnauthorizedError  # noqa: E402


def _page(names: list[str], total_pages: int) -> SimpleNamespace:
    return SimpleNamespace(data=[SimpleNamespace(name=n) for n in names], meta=SimpleNamespace(total_pages=total_pages))


class StubSdk:
    def __init__(self, pages: list[list[str]] | None = None, error: Exception | None = None) -> None:
        self.pages, self.error = pages or [[]], error
        self.created: list[dict[str, Any]] = []
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
