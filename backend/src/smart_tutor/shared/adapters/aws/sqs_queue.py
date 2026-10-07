"""MessageQueue on SQS (long polling)."""

from typing import TYPE_CHECKING

from smart_tutor.shared.ports.message_queue import MessageQueue, QueueMessage

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient


class SqsMessageQueue(MessageQueue):
    def __init__(self, client: "SQSClient", queue_url: str, wait_seconds: int = 20) -> None:
        self._client, self._url, self._wait = client, queue_url, wait_seconds

    def receive(self) -> list[QueueMessage]:
        response = self._client.receive_message(QueueUrl=self._url, MaxNumberOfMessages=1, WaitTimeSeconds=self._wait)
        return [QueueMessage(m["ReceiptHandle"], m["Body"]) for m in response.get("Messages", [])]

    def send(self, body: str) -> None:
        self._client.send_message(QueueUrl=self._url, MessageBody=body)

    def delete(self, message: QueueMessage) -> None:
        self._client.delete_message(QueueUrl=self._url, ReceiptHandle=message.receipt)
