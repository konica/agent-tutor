"""Object storage for uploads and contents (S3 in production, LocalStack locally)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ObjectNotFoundError(Exception):
    """No object at that key."""


@dataclass(frozen=True)
class PresignedPost:
    """Where and how the browser POSTs a file: the form fields go first, the file last."""

    url: str
    fields: dict[str, str]


class ObjectStore(ABC):
    @abstractmethod
    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        """A POST that stores exactly `key`, only with this content type and 1..max_bytes bytes."""

    @abstractmethod
    def presign_get(self, key: str, *, expires_in: int) -> str:
        """A link that serves `key` as a PDF to whoever holds it for `expires_in` seconds."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """The object's bytes; raises ObjectNotFoundError."""

    @abstractmethod
    def put(self, key: str, data: bytes, content_type: str) -> None:
        """Store `data` at `key`, replacing any object there."""

    @abstractmethod
    def copy(self, source_key: str, dest_key: str) -> None:
        """Copy within the bucket (same bytes at `dest_key`)."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete; a missing object is not an error."""

    @abstractmethod
    def delete_all_versions(self, key: str) -> None:
        """Delete every stored version and delete marker of exactly `key` (the bucket is versioned, PRD §9.5).

        A missing key is not an error.
        """
