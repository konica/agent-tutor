"""One conversation (PRD §9.4 Thread). It has no subjects; it keeps its documents used (US-4b)."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.tutoring.domain.errors import InvalidTitleError, NoListedDocumentsError, ThreadArchivedError

MAX_TITLE = 120
CHANGE_ARCHIVED = "An archived conversation can't be changed. Restore it first."


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

    @property
    def last_activity(self) -> datetime:
        """The learner's last question in it, or when it started (US-13)."""
        return self.last_learner_message_at or self.created_at

    def ask(self, now: datetime) -> None:
        """The learner asks in it now; an archived thread is read-only."""
        self.require_active("An archived conversation is read-only. Restore it first.")
        self.last_learner_message_at = now

    def archive(self) -> None:
        """The learner archives it (US-13): read-only until restored; history, documents used, and title stay."""
        self.status = ThreadStatus.ARCHIVED

    def restore(self) -> None:
        """The learner restores it: it can be asked in, renamed, and changed again."""
        self.status = ThreadStatus.ACTIVE

    def require_active(self, message: str) -> None:
        """An archived thread is read-only (US-13)."""
        if self.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError(message)

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.user_id == user_id

    def rename(self, title: str) -> str:
        """The learner's title, trimmed, 1-120 characters (US-13); returns it. An archived thread can't be renamed."""
        self.require_active("An archived conversation can't be renamed. Restore it first.")
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
        self.require_active(CHANGE_ARCHIVED)
        if scope is SearchScope.LISTED and listed == 0:
            raise NoListedDocumentsError("Add documents to limit the search.")
        self.search_scope = scope
