from smart_tutor.shared.ports.message_queue import MessageQueue, QueueMessage


class FakeQueue(MessageQueue):
    def __init__(self, *bodies: str, fail_send: bool = False) -> None:
        self.waiting = [QueueMessage(f"r{i}", body) for i, body in enumerate(bodies)]
        self.deleted: list[QueueMessage] = []
        self.sent: list[QueueMessage] = []
        self._fail_send = fail_send

    def receive(self) -> list[QueueMessage]:
        return self.waiting[:1]  # one at a time, in order

    def send(self, body: str) -> None:
        if self._fail_send:
            raise RuntimeError("queue down")
        message = QueueMessage(f"s{len(self.sent)}", body)
        self.sent.append(message)
        self.waiting.append(message)

    def delete(self, message: QueueMessage) -> None:
        self.waiting.remove(message)
        self.deleted.append(message)
