import pytest

from fakes import FakeParameterStore
from smart_tutor.tutoring.application import DetectionPolicy, load_detection_policy


def test_loads_the_three_values() -> None:
    store = FakeParameterStore({"/t": "0.35", "/m": "0.05", "/mm": "0.03"})

    assert load_detection_policy(store, "/t", "/m", "/mm") == DetectionPolicy(0.35, 0.05, 0.03)


@pytest.mark.parametrize("bad", ["", "abc", "-0.1", "1.5", "nan", "inf"])
def test_a_value_outside_0_to_1_stops_startup(bad: str) -> None:
    store = FakeParameterStore({"/t": bad, "/m": "0.05", "/mm": "0.03"})

    with pytest.raises(ValueError, match="/t"):
        load_detection_policy(store, "/t", "/m", "/mm")
