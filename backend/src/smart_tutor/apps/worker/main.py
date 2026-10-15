"""Ingestion worker: read S3 upload events and Library retries from SQS, roughly in order, and hand each to
IngestionService (PRD §9.5).

One message at a time (plain FIFO, no per-learner fairness). A message is deleted only after it was handled;
a failure leaves it to come back after the visibility timeout, and the queue's redrive policy moves it to the
DLQ after 5 receives. Each content's processing is traced as `ingest` into `<phoenix_project>-ingestion` in Phoenix,
with the content id and learner hash.
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
from smart_tutor.knowledge.adapters.time_limited_extractor import TimeLimitedExtractor
from smart_tutor.knowledge.application import (
    DocumentDescriber,
    IngestionService,
    ProcessingTools,
    StartIndexBackfill,
    load_file_limits,
    retried_content,
)
from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client, ssm_client
from smart_tutor.shared.adapters.aws.sqs_queue import SqsMessageQueue
from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.tracing import OtelRunTracing, ingestion_project, start_tracing
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.message_queue import MessageQueue
from smart_tutor.shared.ports.run_tracing import NoRunTracing
from smart_tutor.subjects.adapters.sql_subjects import SqlSubjectRepository
from smart_tutor.subjects.application import SubjectCatalogService

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
        retried = retried_content(message.body)  # Retry from the Library (PRD §9.5)
        keys = [] if retried else upload_keys(message.body)
        try:
            if retried:
                ingestion.process_content(retried)
            for key in keys:
                ingestion.ingest_upload(key)
        except Exception:
            logger.exception("ingestion failed for %s; the message will be redelivered", retried or keys)
            continue
        queue.delete(message)
    return len(messages)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    traces = start_tracing(settings, ingestion_project(settings))  # refuses tracing without a learner-hash key
    tracing = OtelRunTracing(traces) if traces else NoRunTracing()
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    chunker, chunker_id = build_chunker(settings.chunking)
    models = ModelFactory(settings)
    embedding = settings.models.embedding
    embeddings = models.embedding()
    tools = ProcessingTools(
        extractor=TimeLimitedExtractor(PypdfExtractor(), settings.extraction_timeout_seconds),
        describer=DocumentDescriber(models.chat(ChatRole.AGENT)),  # PRD §9.13: document description
        chunker=chunker,
        chunker_id=chunker_id,
        embeddings=embeddings,
        embedding_model=embedding.model_id,
        embedding_dim=embedding_dimension(embedding.params),
        tracing=tracing,
    )
    backfilled = SubjectCatalogService(SqlSubjectRepository(engine), embeddings).embed_missing_names()
    logger.info("embedded %d subject names", backfilled)
    limits = load_file_limits(
        SsmParameterStore(ssm_client(settings)), settings.max_upload_mb_param, settings.max_pages_param
    )
    library_objects = S3ObjectStore(s3_client(settings), settings.documents_bucket)
    offsets = StartIndexBackfill(library, library_objects).run()  # chunks from before start_index (#124)
    logger.info("start_index backfill: %d located, %d left null", offsets.located, offsets.missing)
    ingestion = IngestionService(library, library_objects, tools, limits)
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
    if traces:
        traces.shutdown()  # send what is left


if __name__ == "__main__":
    main()
