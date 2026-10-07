"""Services the API's routes call, built once per process (tests pass fakes to create_app instead)."""

from dataclasses import dataclass

import httpx

from smart_tutor.apps.api.agent_client import AgentClient
from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import (
    DocumentService,
    RetryService,
    SubjectChoiceService,
    UploadService,
    load_file_limits,
    load_max_attempts,
)
from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client, ssm_client
from smart_tutor.shared.adapters.aws.sqs_queue import SqsMessageQueue
from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.adapters.clock import SystemClock
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.subjects.adapters.sql_subjects import SqlSubjectRepository
from smart_tutor.subjects.application import SubjectCatalogService, SubjectNames, SubjectSuggester
from smart_tutor.tutoring.adapters.sql_threads import SqlThreadRepository
from smart_tutor.tutoring.application import ConversationService


@dataclass(frozen=True)
class ApiServices:
    uploads: UploadService
    documents: DocumentService
    subjects: SubjectNames
    retries: RetryService
    subject_choice: SubjectChoiceService
    conversations: ConversationService
    agent: AgentClient


def build_services(settings: Settings) -> ApiServices:
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    objects = S3ObjectStore(s3_client(settings), settings.documents_bucket)
    params = SsmParameterStore(ssm_client(settings))
    limits = load_file_limits(params, settings.max_upload_mb_param, settings.max_pages_param)
    max_attempts = load_max_attempts(params, settings.max_processing_attempts_param)
    queue = SqsMessageQueue(sqs_client(settings), settings.ingest_queue_url)
    subject_repo = SqlSubjectRepository(engine)
    names = SubjectNames(subject_repo)
    documents = DocumentService(library, max_attempts)
    return ApiServices(
        uploads=UploadService(library, objects, SystemClock(), limits),
        documents=documents,
        subjects=names,
        retries=RetryService(library, queue, max_attempts),
        subject_choice=SubjectChoiceService(
            library,
            SubjectSuggester(subject_repo, names),
            SubjectCatalogService(subject_repo, ModelFactory(settings).embedding()),
            max_attempts,
        ),
        conversations=ConversationService(SqlThreadRepository(engine), documents, SystemClock()),
        # Answers stream for a while: a long read timeout between SSE events, a short one to connect.
        agent=AgentClient(settings.agent_url, httpx.AsyncClient(timeout=httpx.Timeout(10, read=120))),
    )
