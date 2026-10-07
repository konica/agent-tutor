"""A work queue (SQS): receive, then delete once handled; undeleted messages come back after a timeout."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueMessage:
    receipt: str
    body: str


class MessageQueue(ABC):
    @abstractmethod
    def receive(self) -> list[QueueMessage]:
        """Wait briefly for messages, roughly oldest first; may return none."""

    @abstractmethod
    def send(self, body: str) -> None:
        """Add a message at the back of the queue."""

    @abstractmethod
    def delete(self, message: QueueMessage) -> None: ...
