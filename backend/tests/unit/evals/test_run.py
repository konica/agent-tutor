from evals.detection_dataset import DetectionItem
from evals.run import RemoteExample, plan_sync


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
