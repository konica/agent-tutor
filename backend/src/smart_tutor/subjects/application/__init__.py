"""subjects.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.subjects.application.subject_names import SubjectNames
from smart_tutor.subjects.domain.subject import GENERAL_SUBJECT_ID
from smart_tutor.subjects.ports.subject_repository import SubjectRepository

__all__ = ["GENERAL_SUBJECT_ID", "SubjectNames", "SubjectRepository"]
