from evals.gate import failures, load_thresholds, targets


def test_targets_read_release_1_subject_detection_from_the_real_file() -> None:
    assert targets(load_thresholds(), "release_1", "subject_detection") == {
        "exact_set": ("min", 0.90),
        "contains_wrong": ("max", 0.03),
        "asked_when_clear": ("max", 0.10),
    }


def test_failures_name_each_missed_or_missing_metric() -> None:
    goal = {"exact_set": ("min", 0.9), "contains_wrong": ("max", 0.03), "asked_when_clear": ("max", 0.1)}
    assert failures({"exact_set": 0.9, "contains_wrong": 0.03, "asked_when_clear": 0.1}, goal) == []
    found = failures({"exact_set": 0.89, "contains_wrong": 0.05}, goal)
    assert len(found) == 3 and all(any(m in f for m in goal) for f in found)
