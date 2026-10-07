"""Errors of the tutoring module; the API maps them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class ThreadSubjectsError(DomainError):
    """A thread holds 1 to 3 distinct subjects, and subjects are only ever added."""


class NoDocumentsError(DomainError):
    """The learner has no ready documents to answer from (PRD §8 US-3)."""


class RetrievalError(Exception):
    """Search failed for a reason other than the token (MCP unreachable, tool error). Never holds the token."""
