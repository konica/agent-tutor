import pytest

from fakes import FakeParameterStore
from smart_tutor.knowledge.application import FileLimits, load_file_limits
from smart_tutor.knowledge.domain.limits import MIB
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError

MB, PAGES = "/smart-tutor/max-upload-mb", "/smart-tutor/max-pages"


def test_reads_megabytes_and_pages_from_parameters() -> None:
    store = FakeParameterStore({MB: "50", PAGES: "500"})

    assert load_file_limits(store, MB, PAGES) == FileLimits(max_bytes=50 * MIB, max_pages=500)


@pytest.mark.parametrize("bad", ["abc", "0", "-3", "1.5", ""])
def test_a_bad_value_names_the_parameter(bad: str) -> None:
    store = FakeParameterStore({MB: "50", PAGES: bad})

    with pytest.raises(ValueError, match="/smart-tutor/max-pages"):
        load_file_limits(store, MB, PAGES)


def test_a_missing_parameter_is_not_defaulted() -> None:
    with pytest.raises(ParameterNotFoundError, match="/smart-tutor/max-upload-mb"):
        load_file_limits(FakeParameterStore({PAGES: "500"}), MB, PAGES)


@pytest.mark.parametrize(("size", "pages"), [(0, 1), (1, 0)])
def test_limits_must_be_positive(size: int, pages: int) -> None:
    with pytest.raises(ValueError):
        FileLimits(max_bytes=size, max_pages=pages)
