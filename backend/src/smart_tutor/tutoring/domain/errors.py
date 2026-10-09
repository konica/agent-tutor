"""Errors of the tutoring module; the API maps them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class NoDocumentsError(DomainError):
    """The learner has no ready documents to answer from (PRD §8 US-3)."""


class DocumentNotAvailableError(DomainError):
    """The document isn't the learner's ready, non-archived document, so it can't join a conversation (US-4c)."""


class RetrievalError(Exception):
    """Search failed for a reason other than the token (MCP unreachable, tool error). Never holds the token."""


class ThreadNotFoundError(DomainError):
    """The thread doesn't exist or isn't the learner's."""


class InvalidTitleError(DomainError):
    """A conversation title must be 1-120 characters once trimmed (PRD §8 US-13)."""


class ThreadArchivedError(DomainError):
    """An archived conversation is read-only until it is restored (PRD §8 US-13)."""
