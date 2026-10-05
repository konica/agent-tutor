"""Hash an uploaded file on the server, store its content once, and process it (PRD §9.5; ADR 0002, 0008).

Processing: extract the page text, save it as JSON, chunk, embed, then make the content and the learner's
document ready. Crashes (S3, Bedrock, database) are raised so SQS redelivers the message; only a file we
can't read, or one with no text layer, ends failed.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.documents import BaseDocumentTransformer
from langchain_core.documents import Document as TextDocument
from langchain_core.embeddings import Embeddings

from smart_tutor.knowledge.application.upload_service import new_uuid
from smart_tutor.knowledge.domain.chunk import Chunk, validate_chunk
from smart_tutor.knowledge.domain.content import (
    NO_TEXT_LAYER,
    UNREADABLE_PDF,
    Content,
    ContentState,
    has_text_layer,
    pages_key,
)
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, DocumentState
from smart_tutor.knowledge.domain.upload import UploadOutcome, parse_upload_key
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore
from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor, UnreadablePdfError
from smart_tutor.shared.domain.ids import ContentId, UploadId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingTools:
    """What turns a stored PDF into embedded chunks; the ids are recorded on the content."""

    extractor: PdfExtractor
    chunker: BaseDocumentTransformer
    chunker_id: str
    embeddings: Embeddings
    embedding_model: str
    embedding_dim: int


class IngestionService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        tools: ProcessingTools,
        new_id: Callable[[], str] = new_uuid,
    ) -> None:
        self._uow, self._objects, self._tools, self._new_id = uow, objects, tools, new_id

    def ingest_upload(self, key: str) -> UploadOutcome | None:
        """Store or reject one uploaded file. None means there was nothing new to store (not ours, or already handled).

        A new content, or a redelivery whose content is still processing (a crash during processing), is then
        processed. Processing errors propagate so the message stays for redelivery.
        """
        parsed = parse_upload_key(key)
        if parsed is None:
            logger.warning("ignoring a non-upload key")
            return None
        outcome, to_process = self._store(key, *parsed)
        if to_process is not None:
            self.process_content(to_process)
        return outcome

    def _store(self, key: str, user_id: UserId, upload_id: UploadId) -> tuple[UploadOutcome | None, ContentId | None]:
        """The outcome, and the content that still needs processing.

        Everything happens in one transaction that holds the document's row lock and, for a new hash, the
        content's unique key, so a crash before commit leaves the upload to be redelivered and retried.
        """
        with self._uow() as tx:
            document = tx.documents.get_by_upload_for_update(upload_id)
            if document is None or not document.can_be_read_by(user_id):
                logger.warning("no document for upload %s under this learner; ignoring", upload_id)
                return None, None
            if not document.awaiting_upload:
                logger.info("upload %s was already handled", upload_id)
                self._objects.delete(key)
                unfinished = document.state is DocumentState.PROCESSING
                return None, document.content_id if unfinished else None
            try:
                data = self._objects.read(key)
            except ObjectNotFoundError:
                logger.warning("upload %s has no object", upload_id)
                return None, None
            sha256 = hashlib.sha256(data).hexdigest()
            content, created = tx.contents.insert_or_get(
                Content.first_upload(ContentId(self._new_id()), sha256, len(data), user_id)
            )
            if created:
                self._objects.copy(key, content.s3_key)
                document.link_content(content.content_id)
                outcome = UploadOutcome.STORED
            else:
                # Until US-11 links duplicates. content_id stays null: (owner_id, content_id) is unique.
                document.fail(DUPLICATE_UPLOAD)
                outcome = UploadOutcome.DUPLICATE
            tx.documents.save(document)
            tx.uploads.record_outcome(upload_id, len(data), outcome)
            tx.commit()
        self._objects.delete(key)
        logger.info("upload %s: %s", upload_id, outcome.value)
        return outcome, content.content_id if created else None

    def process_content(self, content_id: ContentId) -> ContentState | None:
        """Turn a stored content into embedded chunks and make it, and the documents waiting on it, ready.

        None when the content is missing or no longer processing (someone else finished it). Extraction and
        embedding run with no transaction open, so no lock is held across slow calls; the final transaction
        rechecks the state under lock.
        """
        with self._uow() as tx:
            content = tx.contents.get(content_id)
        if content is None or content.state is not ContentState.PROCESSING:
            return None
        try:
            pages = self._tools.extractor.extract_pages(self._objects.read(content.s3_key))
        except UnreadablePdfError:
            return self._fail(content_id, UNREADABLE_PDF)
        if not has_text_layer(pages):
            return self._fail(content_id, NO_TEXT_LAYER)
        chunks = self._chunks(content_id, pages)
        if not chunks:
            return self._fail(content_id, NO_TEXT_LAYER)
        text_key = pages_key(content.sha256)
        listing = {"pages": [{"page": number, "text": text} for number, text in enumerate(pages, start=1)]}
        self._objects.put(text_key, json.dumps(listing, ensure_ascii=False).encode(), "application/json")

        with self._uow() as tx:
            locked = tx.contents.get_for_update(content_id)
            if locked is None or locked.state is not ContentState.PROCESSING:
                return None
            tx.chunks.replace(content_id, chunks)
            locked.ready(
                pages=len(pages),
                text_key=text_key,
                chunker=self._tools.chunker_id,
                embedding_model=self._tools.embedding_model,
                embedding_dim=self._tools.embedding_dim,
            )
            tx.contents.save(locked)
            for document in tx.documents.list_processing_for_content_for_update(content_id):
                document.ready([GENERAL_SUBJECT_ID])
                tx.documents.save(document)
            tx.commit()
        logger.info("content %s: ready with %d chunks", content_id, len(chunks))
        return ContentState.READY

    def _chunks(self, content_id: ContentId, pages: list[str]) -> list[Chunk]:
        """Chunk each non-blank page (keeping its physical number), check every chunk, and embed them."""
        sources = [
            TextDocument(page_content=text, metadata={"page": number})
            for number, text in enumerate(pages, start=1)
            if text.strip()
        ]
        pieces = list(self._tools.chunker.transform_documents(sources))
        found = [(validate_chunk(p.metadata.get("page"), p.page_content), p.page_content) for p in pieces]
        if not found:
            return []
        vectors = self._tools.embeddings.embed_documents([text for _, text in found])
        dim = self._tools.embedding_dim
        if len(vectors) != len(found) or any(len(v) != dim for v in vectors):
            raise ValueError(f"The embedding model must return {dim} floats per chunk (dimension mismatch)")
        return [
            Chunk(content_id, seq, page, text, v)
            for seq, ((page, text), v) in enumerate(zip(found, vectors, strict=True))
        ]

    def _fail(self, content_id: ContentId, reason: str) -> ContentState | None:
        with self._uow() as tx:
            content = tx.contents.get_for_update(content_id)
            if content is None or content.state is not ContentState.PROCESSING:
                return None
            content.fail(reason)
            tx.contents.save(content)
            for document in tx.documents.list_processing_for_content_for_update(content_id):
                document.fail(reason)
                tx.documents.save(document)
            tx.commit()
        logger.info("content %s: failed (%s)", content_id, reason)
        return ContentState.FAILED
