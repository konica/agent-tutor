"""Ingestion worker: read S3 upload events from SQS in order and hand each upload to IngestionService (PRD §9.5).

One message at a time (plain FIFO, no per-learner fairness). A message is deleted only after it was handled;
a failure leaves it to come back after the visibility timeout, and the queue's redrive policy moves it to the
DLQ after 5 receives.
"""

import logging
import signal
import threading

from smart_tutor.apps.worker.events import upload_keys
from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import IngestionService
from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client
from smart_tutor.shared.adapters.aws.sqs_queue import SqsMessageQueue
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.message_queue import MessageQueue

logger = logging.getLogger(__name__)


def run_once(queue: MessageQueue, ingestion: IngestionService) -> int:
    messages = queue.receive()
    for message in messages:
        try:
            for key in upload_keys(message.body):
                ingestion.ingest_upload(key)
        except Exception:
            logger.exception("ingestion failed; the message will be redelivered")
            continue
        queue.delete(message)
    return len(messages)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    ingestion = IngestionService(library, S3ObjectStore(s3_client(settings), settings.documents_bucket))
    queue = SqsMessageQueue(sqs_client(settings), settings.ingest_queue_url)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    logger.info("worker started")
    while not stop.is_set():
        run_once(queue, ingestion)


if __name__ == "__main__":
    main()
