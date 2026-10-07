"""Choose a document's subjects from its suggestions or typed names (PRD §8 US-2b, D20, §9.2 step 5; ADR 0004)."""

from collections.abc import Callable
from dataclasses import dataclass

from smart_tutor.knowledge.application.document_service import DocumentView, document_view
from smart_tutor.knowledge.domain.document import MAX_SUBJECTS, Document, DocumentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError, DocumentStateError, InvalidSubjectsError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import (
    CatalogMatch,
    InvalidSubjectNameError,
    SubjectCatalogService,
    SubjectSearch,
    SubjectSuggester,
    Suggestion,
    normalize_subject_name,
)

CHOOSABLE = (DocumentState.AWAITING_SUBJECTS, DocumentState.READY)
NOT_DIFFERENT = "Choose 1 to 3 different subjects"


@dataclass(frozen=True)
class SubjectSuggestions:
    document_id: DocumentId
    title: str
    summary: str | None
    suggestions: list[Suggestion]


class SubjectChoiceService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        suggester: SubjectSuggester,
        catalog: SubjectCatalogService,
        search: SubjectSearch,
        max_attempts: int,
    ) -> None:
        self._uow = uow
        self._suggester = suggester
        self._catalog = catalog
        self._search = search
        self._max_attempts = max_attempts  # shown in the returned view, like DocumentService.list_documents

    def suggestions(self, user_id: UserId, document_id: DocumentId) -> SubjectSuggestions:
        with self._uow() as tx:
            document = self._choosable(tx, user_id, document_id)
            content = tx.contents.get(document.content_id) if document.content_id else None
            yours = tx.documents.subject_ids_readable_by(user_id)
        suggestions = self._suggester.suggest(
            user_id,
            content.summary_embedding if content else None,
            content.proposed_subject_names if content else [],
            yours,
        )
        return SubjectSuggestions(
            document.document_id, document.title, content.summary if content else None, suggestions
        )

    def search(self, user_id: UserId, query: str) -> list[CatalogMatch]:
        """Type-ahead over the shared catalog: the learner's subjects (ready documents) first."""
        with self._uow() as tx:
            yours = tx.documents.subject_ids_readable_by(user_id)
        return self._search.search(user_id, query, yours)

    def choose(
        self, user_id: UserId, document_id: DocumentId, subject_ids: list[SubjectId], new_names: list[str]
    ) -> DocumentView:
        if not 1 <= len(subject_ids) + len(new_names) <= MAX_SUBJECTS:
            raise InvalidSubjectsError(NOT_DIFFERENT)
        with self._uow() as tx:
            self._choosable(tx, user_id, document_id)  # 404/409 before creating anything
        if self._catalog.unknown(subject_ids):
            raise InvalidSubjectsError("Unknown subject")
        if len({normalize_subject_name(n) for n in new_names}) != len(new_names) or len(set(subject_ids)) != len(
            subject_ids
        ):
            raise InvalidSubjectsError(NOT_DIFFERENT)  # before creating anything
        # Subjects live in another module's store, so they are created before the document transaction. One that
        # ends up unused is harmless: it is a shared name.
        try:
            created = [self._catalog.get_or_create(name) for name in new_names]
        except InvalidSubjectNameError as e:
            raise InvalidSubjectsError(str(e)) from None
        with self._uow() as tx:
            document = self._choosable(tx, user_id, document_id, for_update=True)
            document.choose_subjects([*subject_ids, *created])  # rejects a new name that resolved to a chosen id
            tx.documents.save(document)
            tx.commit()
        return document_view(document, self._max_attempts)

    @staticmethod
    def _choosable(
        tx: LibraryUnitOfWork, user_id: UserId, document_id: DocumentId, *, for_update: bool = False
    ) -> Document:
        document = tx.documents.get_readable(user_id, document_id, for_update=for_update)
        if document is None:
            raise DocumentNotFoundError("This document isn't in your library")
        if document.state not in CHOOSABLE:
            raise DocumentStateError("Subjects can be chosen once processing has finished")
        return document
