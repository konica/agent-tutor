"""Services the API's routes call, built once per process (tests pass fakes to create_app instead)."""

from dataclasses import dataclass

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.adapters.aws.clients import s3_client
from smart_tutor.shared.adapters.clock import SystemClock
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.subjects.adapters.sql_subjects import SqlSubjectRepository
from smart_tutor.subjects.application import SubjectNames


@dataclass(frozen=True)
class ApiServices:
    uploads: UploadService
    documents: DocumentService
    subjects: SubjectNames


def build_services(settings: Settings) -> ApiServices:
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    objects = S3ObjectStore(s3_client(settings), settings.documents_bucket)
    return ApiServices(
        uploads=UploadService(library, objects, SystemClock()),
        documents=DocumentService(library),
        subjects=SubjectNames(SqlSubjectRepository(engine)),
    )
