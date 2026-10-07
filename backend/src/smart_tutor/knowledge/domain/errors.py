"""Errors of the knowledge module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidFileNameError(DomainError):
    """The upload has no usable file name."""


class DocumentStateError(DomainError):
    """The document isn't in a state that allows this change (PRD §9.5)."""


class ContentStateError(DomainError):
    """The content isn't in a state that allows this change (PRD §9.5)."""


class InvalidChunkError(DomainError):
    """A chunker produced a chunk the store must not accept (PRD §9.4)."""


class InvalidSearchError(DomainError):
    """The search request is malformed (query, subjects, or k out of range)."""


class InvalidDescriptionError(DomainError):
    """A describe_document payload failed validation; the message names the field, never its value (PRD §9.9)."""


class RetryLimitError(DomainError):
    """The content used all its processing attempts (PRD §9.5)."""


class DocumentNotFoundError(DomainError):
    """No such document for this learner; entrypoints answer 404 whether it is missing or someone else's."""
