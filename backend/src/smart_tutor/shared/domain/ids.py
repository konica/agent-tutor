"""Typed identifiers shared across modules."""

from typing import NewType

UserId = NewType("UserId", str)  # Keycloak `sub`
ThreadId = NewType("ThreadId", str)
SubjectId = NewType("SubjectId", str)  # e.g. "ielts", "ai-agents" (S3 prefix subjects/<subject>/)
