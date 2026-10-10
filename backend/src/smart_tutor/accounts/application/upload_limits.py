"""Upload limits from SSM (PRD §9.4 Settings), read once at startup by the API."""

from smart_tutor.accounts.domain.upload_limits import UploadLimits
from smart_tutor.shared.ports.parameter_store import ParameterStore


def _positive(store: ParameterStore, name: str) -> int:
    raw = store.get(name)
    if not (raw.isascii() and raw.isdigit()) or int(raw) <= 0:
        raise ValueError(f"{name} must be a positive whole number, got {raw!r}")
    return int(raw)


def load_upload_limits(store: ParameterStore, per_hour_param: str, per_day_param: str) -> UploadLimits:
    return UploadLimits(per_hour=_positive(store, per_hour_param), per_day=_positive(store, per_day_param))
