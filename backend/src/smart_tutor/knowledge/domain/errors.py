"""Errors of the knowledge module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidFileNameError(DomainError):
    """The upload has no usable file name."""


class DocumentStateError(DomainError):
    """The document isn't in a state that allows this change (PRD §9.5)."""
