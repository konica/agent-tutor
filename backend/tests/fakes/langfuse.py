"""The evals' Langfuse seam (evals.langfuse_client.LangfuseClient), in memory: datasets by unique name, their
metadata, and their items in the order created."""

from dataclasses import dataclass, field
from typing import Any

from evals.langfuse_client import Item, LangfuseError, StoredDataset


@dataclass
class _Dataset:
    description: str
    metadata: dict[str, Any]
    items: list[Item] = field(default_factory=list)


class FakeLangfuse:
    def __init__(self) -> None:
        self.datasets: dict[str, _Dataset] = {}
        self.calls = 0  # every call, so a test can see what a dry run did

    def dataset_names(self) -> list[str]:
        self.calls += 1
        return list(self.datasets)

    def get_dataset(self, name: str) -> StoredDataset | None:
        self.calls += 1
        found = self.datasets.get(name)
        if found is None:
            return None
        return StoredDataset(name, dict(found.metadata), tuple(found.items))

    def create_dataset(self, name: str, *, description: str, metadata: dict[str, Any]) -> None:
        self.calls += 1
        if name in self.datasets:  # Langfuse would update it: publishing never overwrites a version
            raise LangfuseError(f"409: dataset {name} exists")
        self.datasets[name] = _Dataset(description, dict(metadata))

    def create_item(self, dataset_name: str, item: Item) -> None:
        self.calls += 1
        if dataset_name not in self.datasets:
            raise LangfuseError(f"404: no dataset {dataset_name}")
        self.datasets[dataset_name].items.append(item)
