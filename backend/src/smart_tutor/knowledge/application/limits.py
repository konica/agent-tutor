"""Load the per-file limits from settings (SSM), never from code (PRD §9.12)."""

from smart_tutor.knowledge.domain.limits import MIB, FileLimits
from smart_tutor.shared.ports.parameter_store import ParameterStore


def _positive(store: ParameterStore, name: str) -> int:
    value = store.get(name)
    if not (value.isascii() and value.isdigit()) or int(value) <= 0:
        raise ValueError(f"SSM parameter {name} must be a positive whole number, got {value!r}")
    return int(value)


def load_file_limits(store: ParameterStore, max_upload_mb_param: str, max_pages_param: str) -> FileLimits:
    return FileLimits(
        max_bytes=_positive(store, max_upload_mb_param) * MIB, max_pages=_positive(store, max_pages_param)
    )


def load_max_attempts(store: ParameterStore, param: str) -> int:
    """Processing attempts per content, Retry and re-upload included (PRD §9.5)."""
    return _positive(store, param)
