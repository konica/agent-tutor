"""Retry a failed document: its content (the owner's own copy) gets another attempt from the stored file (PRD §9.5).

The worker is woken by a message on the ingest queue. It is sent before the commit, while this transaction holds
the content's row lock; the worker's first read locks the content too, so it waits for the commit. If the commit
fails, the worker finds the content still failed and drops the message; nothing was used up.

Locks are taken in the worker's order (the content, then its documents in id order), so two retries of the same
content (documents linked to it are the owner's) cannot deadlock. The caller's document is first read without a lock.
"""

import json
from collections.abc import Callable

from smart_tutor.knowledge.domain.content import ContentState
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UserId
from smart_tutor.shared.ports.message_queue import MessageQueue

_KEY = "retry_content_id"


def retry_message(content_id: ContentId) -> str:
    return json.dumps({_KEY: content_id})


def retried_content(body: str) -> ContentId | None:
    """The content a retry message asks to process; None for any other message."""
    try:
        message = json.loads(body)
    except json.JSONDecodeError:
        return None
    value = message.get(_KEY) if isinstance(message, dict) else None
    return ContentId(value) if isinstance(value, str) and value else None


class RetryService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], queue: MessageQueue, max_attempts: int) -> None:
        self._uow, self._queue, self._max_attempts = uow, queue, max_attempts

    def retry(self, user_id: UserId, document_id: DocumentId) -> None:
        """Raises DocumentNotFoundError (missing or not the caller's) and RetryLimitError.

        A document that isn't failed, or has no content, is left alone.
        """
        with self._uow() as tx:
            document = tx.documents.get(document_id)
            if document is None or not document.can_be_read_by(user_id):
                raise DocumentNotFoundError("Document not found")
            if document.state is not DocumentState.FAILED or document.content_id is None:
                return
            content = tx.contents.get_for_update(document.content_id)
            if content is None or content.state is not ContentState.FAILED:
                return
            failed = tx.documents.list_failed_for_content_for_update(content.content_id)
            if document_id not in {d.document_id for d in failed}:
                return  # it changed between the read and the locks
            content.retry(self._max_attempts)
            tx.contents.save(content)
            for linked in failed:
                linked.retry()
                tx.documents.save(linked)
            self._queue.send(retry_message(content.content_id))
            tx.commit()
