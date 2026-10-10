"""One conversation (PRD §9.4 Thread). It has no subjects; it keeps its documents used (US-4b)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.tutoring.domain.errors import InvalidTitleError, NoListedDocumentsError, ThreadArchivedError

MAX_TITLE = 120


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class SearchScope(StrEnum):
    LIBRARY = "library"
    LISTED = "listed"


@dataclass
class Thread:
    thread_id: ThreadId
    user_id: UserId
    created_at: datetime
    status: ThreadStatus = ThreadStatus.ACTIVE
    title: str | None = None
    search_scope: SearchScope = SearchScope.LIBRARY
    last_learner_message_at: datetime | None = None

    @classmethod
    def start(cls, thread_id: ThreadId, user_id: UserId, now: datetime, title: str | None = None) -> "Thread":
        """A new thread with its first question asked now; its title starts as that question (§9.4)."""
        return cls(thread_id, user_id, now, title=title, last_learner_message_at=now)

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.user_id == user_id

    def rename(self, title: str) -> str:
        """The learner's title, trimmed, 1-120 characters (US-13); returns it. An archived thread can't be renamed."""
        if self.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError("An archived conversation can't be renamed. Restore it first.")
        trimmed = title.strip()
        if not trimmed:
            raise InvalidTitleError("Enter a title")
        if len(trimmed) > MAX_TITLE:
            raise InvalidTitleError(f"Use at most {MAX_TITLE} characters")
        self.title = trimmed
        return trimmed

    def limit_search(self, scope: SearchScope, listed: int) -> None:
        """Search all ready documents or only the listed ones (US-4c); limiting needs a listed document. An archived
        thread can't be changed."""
        if self.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError("An archived conversation can't be changed. Restore it first.")
        if scope is SearchScope.LISTED and listed == 0:
            raise NoListedDocumentsError("Add documents to limit the search.")
        self.search_scope = scope
