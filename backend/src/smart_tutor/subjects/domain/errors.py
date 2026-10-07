"""Errors of the subjects module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidSubjectNameError(DomainError):
    """A subject name is empty or longer than 60 characters (PRD US-2b)."""
