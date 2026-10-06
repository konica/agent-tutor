"""Errors of the knowledge module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidFileNameError(DomainError):
    """The upload has no usable file name."""


class DocumentStateError(DomainError):
    """The document isn't in a state that allows this change (PRD §9.5)."""


class InvalidSubjectsError(DomainError):
    """The chosen subjects aren't 1 to 3 different subjects (PRD §9.4)."""


class DocumentNotFoundError(DomainError):
    """No document of the caller's has this id; another learner's document looks the same (PRD §9.3)."""


class ContentStateError(DomainError):
    """The content isn't in a state that allows this change (PRD §9.5)."""


class InvalidChunkError(DomainError):
    """A chunker produced a chunk the store must not accept (PRD §9.4)."""


class InvalidDescriptionError(DomainError):
    """A describe_document payload failed validation; the message names the field, never its value (PRD §9.9)."""
