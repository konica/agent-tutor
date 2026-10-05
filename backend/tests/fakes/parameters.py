from smart_tutor.knowledge.domain.limits import MIB, FileLimits
from smart_tutor.shared.ports.parameter_store import ParameterNotFoundError, ParameterStore

TEST_LIMITS = FileLimits(max_bytes=50 * MIB, max_pages=500)


class FakeParameterStore(ParameterStore):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str) -> str:
        if name not in self._values:
            raise ParameterNotFoundError(name)
        return self._values[name]
