from types import SimpleNamespace
from typing import Any

import pytest

from evals.detection_dataset import DetectionItem
from evals.run import RemoteExample, RowOutcome, plan_sync, row_failures, sync_dataset
from evals.targets import parse_policy
from evals.tune_detection import _frange
from smart_tutor.tutoring.domain.detection import DetectionPolicy


class FakeClient:
    def __init__(self, remote: list[Any] | None = None, has: bool = True) -> None:
        self.remote = remote or []
        self.has = has
        self.calls: list[tuple[str, Any]] = []

    def has_dataset(self, *, dataset_name: str) -> bool:
        return self.has

    def create_dataset(self, name: str, **kwargs: Any) -> None:
        self.calls.append(("create_dataset", name))

    def list_examples(self, *, dataset_name: str) -> list[Any]:
        return self.remote

    def create_examples(self, **kwargs: Any) -> None:
        self.calls.append(("create_examples", kwargs))

    def update_example(self, example_id: str, **kwargs: Any) -> None:
        self.calls.append(("update_example", (example_id, kwargs)))

    def delete_example(self, example_id: str) -> None:
        self.calls.append(("delete_example", example_id))


def example(local: "DetectionItem", example_id: str, splits: list[str]) -> Any:
    return SimpleNamespace(
        id=example_id,
        inputs=local.inputs(),
        outputs=local.reference_outputs(),
        metadata={"item_id": local.id, "kind": local.kind, "dataset_split": splits},
    )


def item(item_id: str, question: str = "q", smoke: bool = False) -> DetectionItem:
    return DetectionItem(item_id, "single", smoke, ("a", "b"), question, ("Math",), ())


def remote(local: DetectionItem, remote_id: str) -> RemoteExample:
    splits = ["smoke", "full"] if local.smoke else ["full"]
    return RemoteExample(remote_id, local.id, local.inputs(), local.reference_outputs(), splits)


def test_new_item_is_created() -> None:
    plan = plan_sync([item("x")], [])
    assert [i.id for i in plan.create] == ["x"]
    assert plan.update == [] and plan.delete == []


def test_equal_items_are_left_alone() -> None:
    a = item("a", smoke=True)
    plan = plan_sync([a], [remote(a, "r1")])
    assert (plan.create, plan.update, plan.delete) == ([], [], [])


def test_changed_question_is_updated() -> None:
    plan = plan_sync([item("a", "new")], [remote(item("a", "old"), "r1")])
    assert [(rid, i.question) for rid, i in plan.update] == [("r1", "new")]


def test_changed_split_membership_is_updated() -> None:
    plan = plan_sync([item("a", smoke=True)], [remote(item("a"), "r1")])
    assert [rid for rid, _ in plan.update] == ["r1"]


def test_remote_item_no_longer_local_is_deleted() -> None:
    plan = plan_sync([], [remote(item("gone"), "r9")])
    assert plan.delete == ["r9"]


def test_sync_creates_with_split_and_metadata() -> None:
    client = FakeClient()
    sync_dataset(client, "ds", [item("a", smoke=True)])  # type: ignore[arg-type]
    [(name, kwargs)] = client.calls
    assert name == "create_examples" and kwargs["dataset_name"] == "ds"
    [payload] = kwargs["examples"]
    assert payload["metadata"] == {"item_id": "a", "kind": "single"}
    assert payload["split"] == ["smoke", "full"]
    assert payload["inputs"] == item("a").inputs()


def test_sync_creates_a_missing_dataset() -> None:
    client = FakeClient(has=False)
    sync_dataset(client, "ds", [])  # type: ignore[arg-type]
    assert client.calls == [("create_dataset", "ds")]


def test_sync_updates_changed_and_deletes_removed_reading_splits_from_metadata() -> None:
    client = FakeClient(
        [
            example(item("a", "old"), "r1", ["full"]),
            example(item("same"), "r2", ["full"]),
            example(item("gone"), "r3", ["full"]),
        ]
    )
    sync_dataset(client, "ds", [item("a", "new"), item("same")])  # type: ignore[arg-type]
    assert [c[0] for c in client.calls] == ["update_example", "delete_example"]
    example_id, kwargs = client.calls[0][1]
    assert example_id == "r1" and kwargs["inputs"]["question"] == "new" and kwargs["split"] == ["full"]
    assert client.calls[1][1] == "r3"


def test_sync_split_change_alone_triggers_update() -> None:
    client = FakeClient([example(item("a"), "r1", ["full"])])
    sync_dataset(client, "ds", [item("a", smoke=True)])  # type: ignore[arg-type]
    assert client.calls[0][1][1]["split"] == ["smoke", "full"]


def ok(item_id: str) -> RowOutcome:
    return RowOutcome(item_id, None, {"contains_wrong": 0.0})


def test_complete_run_has_no_failures() -> None:
    assert row_failures([ok("a"), ok("b")], {"a", "b"}) == []


def test_target_error_is_a_failure_naming_the_item() -> None:
    rows = [ok("a"), RowOutcome("b", "ThrottlingException", {})]
    [message] = row_failures(rows, {"a", "b"})
    assert "b" in message and "ThrottlingException" in message


def test_row_without_contains_wrong_is_a_failure() -> None:
    [message] = row_failures([RowOutcome("a", None, {})], {"a"})
    assert message.startswith("a:")


def test_missing_items_are_reported() -> None:
    [message] = row_failures([ok("a")], {"a", "b", "c"})
    assert "b, c" in message


def test_unexpected_extra_rows_are_reported() -> None:
    assert row_failures([ok("a"), ok("a")], {"a"}) != []


def test_parse_policy() -> None:
    assert parse_policy("0.5,0.05,0.02") == DetectionPolicy(0.5, 0.05, 0.02)
    with pytest.raises(ValueError):
        parse_policy("0.5,0.05")
    with pytest.raises(ValueError):
        parse_policy("a,b,c")


def test_tuning_grids_have_the_expected_sizes_and_endpoints() -> None:
    thresholds, margins, multi = _frange(0.20, 0.80, 0.01), _frange(0.0, 0.15, 0.005), _frange(0.0, 0.10, 0.005)
    assert (len(thresholds), len(margins), len(multi)) == (61, 31, 21)
    assert (thresholds[0], thresholds[-1]) == (0.20, 0.80)
    assert (margins[0], margins[-1]) == (0.0, 0.15)
    assert (multi[0], multi[-1]) == (0.0, 0.10)
