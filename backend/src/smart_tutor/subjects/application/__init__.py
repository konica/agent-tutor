"""subjects.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.subjects.application.catalog import SubjectCatalogService
from smart_tutor.subjects.application.search import SubjectSearch
from smart_tutor.subjects.application.subject_names import SubjectNames
from smart_tutor.subjects.application.suggester import SubjectSuggester
from smart_tutor.subjects.domain.errors import InvalidSubjectNameError
from smart_tutor.subjects.domain.search import SEARCH_LIMIT, CatalogMatch
from smart_tutor.subjects.domain.subject import GENERAL_SUBJECT_ID, Subject, normalize_subject_name
from smart_tutor.subjects.domain.suggestions import Candidate, Suggestion, SuggestionOrigin
from smart_tutor.subjects.ports.subject_repository import SubjectRepository

__all__ = [
    "GENERAL_SUBJECT_ID",
    "SEARCH_LIMIT",
    "Candidate",
    "CatalogMatch",
    "InvalidSubjectNameError",
    "Subject",
    "SubjectCatalogService",
    "SubjectNames",
    "SubjectRepository",
    "SubjectSearch",
    "SubjectSuggester",
    "Suggestion",
    "SuggestionOrigin",
    "normalize_subject_name",
]
