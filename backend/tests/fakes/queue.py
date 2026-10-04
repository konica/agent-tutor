from smart_tutor.shared.ports.message_queue import MessageQueue, QueueMessage


class FakeQueue(MessageQueue):
    def __init__(self, *bodies: str) -> None:
        self.waiting = [QueueMessage(f"r{i}", body) for i, body in enumerate(bodies)]
        self.deleted: list[QueueMessage] = []

    def receive(self) -> list[QueueMessage]:
        return self.waiting[:1]  # one at a time, in order

    def delete(self, message: QueueMessage) -> None:
        self.waiting.remove(message)
        self.deleted.append(message)
