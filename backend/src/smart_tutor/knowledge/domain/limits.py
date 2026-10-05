"""Per-file limits (PRD D24, §11): checked in the browser and by the presigned POST (size) and by the worker (pages)."""

from dataclasses import dataclass

MIB = 1024 * 1024


@dataclass(frozen=True)
class FileLimits:
    max_bytes: int
    max_pages: int

    def __post_init__(self) -> None:
        if self.max_bytes <= 0 or self.max_pages <= 0:
            raise ValueError("File limits must be positive")
