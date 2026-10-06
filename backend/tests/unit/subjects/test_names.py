import pytest

from smart_tutor.subjects.domain.errors import InvalidSubjectNameError
from smart_tutor.subjects.domain.subject import clean_subject_name, normalize_subject_name


def test_clean_collapses_whitespace_and_drops_control_characters() -> None:
    assert clean_subject_name("  Deep‮   Learning\n") == "Deep Learning"


@pytest.mark.parametrize("raw", ["", "   ", "\x00", "x" * 61])
def test_clean_rejects_empty_or_too_long(raw: str) -> None:
    with pytest.raises(InvalidSubjectNameError):
        clean_subject_name(raw)


def test_normalize_is_equal_for_one_name_typed_differently() -> None:
    assert normalize_subject_name("Deep  LEARNING") == normalize_subject_name("deep learning") == "deep learning"
    assert normalize_subject_name("Ｄeep Learning") == "deep learning"  # NFKC: full-width letters
