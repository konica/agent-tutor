"""Ingestion worker: read S3 upload events from SQS, roughly in order, and hand each to IngestionService (PRD §9.5).

One message at a time (plain FIFO, no per-learner fairness). A message is deleted only after it was handled;
a failure leaves it to come back after the visibility timeout, and the queue's redrive policy moves it to the
DLQ after 5 receives.
"""

import logging
import signal
import threading
from typing import Any

from smart_tutor.apps.worker.events import upload_keys
from smart_tutor.knowledge.adapters.chunking import build_chunker
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.adapters.sql_tables import EMBEDDING_DIM
from smart_tutor.knowledge.application import IngestionService, ProcessingTools
from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client
from smart_tutor.shared.adapters.aws.sqs_queue import SqsMessageQueue
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.message_queue import MessageQueue

logger = logging.getLogger(__name__)


def embedding_dimension(params: dict[str, Any]) -> int:
    """The configured embedding size; it must match the chunks.embedding column, so fail at startup if not."""
    if "dimensions" not in params:
        raise ValueError("The embedding model needs params.dimensions (SMART_TUTOR_MODELS__EMBEDDING__PARAMS)")
    dimensions = params["dimensions"]
    if dimensions != EMBEDDING_DIM:
        raise ValueError(f"The embedding dimension is {dimensions}, but the chunks table stores {EMBEDDING_DIM}")
    return EMBEDDING_DIM


def run_once(queue: MessageQueue, ingestion: IngestionService) -> int:
    messages = queue.receive()
    for message in messages:
        keys = upload_keys(message.body)
        try:
            for key in keys:
                ingestion.ingest_upload(key)
        except Exception:
            logger.exception("ingestion failed for %s; the message will be redelivered", keys)
            continue
        queue.delete(message)
    return len(messages)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    chunker, chunker_id = build_chunker(settings.chunking)
    embedding = settings.models.embedding
    tools = ProcessingTools(
        extractor=PypdfExtractor(),
        chunker=chunker,
        chunker_id=chunker_id,
        embeddings=ModelFactory(settings).embedding(),
        embedding_model=embedding.model_id,
        embedding_dim=embedding_dimension(embedding.params),
    )
    ingestion = IngestionService(library, S3ObjectStore(s3_client(settings), settings.documents_bucket), tools)
    queue = SqsMessageQueue(sqs_client(settings), settings.ingest_queue_url)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    logger.info("worker started")
    while not stop.is_set():
        try:
            run_once(queue, ingestion)
        except Exception:
            logger.exception("worker loop failed; retrying in 5 s")
            stop.wait(5)


if __name__ == "__main__":
    main()
