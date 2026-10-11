"""Hash an uploaded file on the server, store it as the learner's content, and process it (PRD §9.5; ADR 0002, 0008).

Processing: describe the first pages (title, metadata, summary embedding, work key; committed at once so the
Library shows the title), extract the page text, save it as JSON, chunk, embed, then make the content and the
learner's document wait for subjects. Crashes (S3, Bedrock, database) are raised so SQS redelivers the message;
only a file over the page limit, one we can't read, one that takes too long to read, or one with no text layer
ends failed.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from langchain_core.documents import BaseDocumentTransformer
from langchain_core.documents import Document as TextDocument
from langchain_core.embeddings import Embeddings

from smart_tutor.knowledge.application.describer import FIRST_PAGES, DocumentDescriber
from smart_tutor.knowledge.domain.chunk import Chunk, start_index_of, validate_chunk
from smart_tutor.knowledge.domain.content import (
    EXTRACTION_TIMED_OUT,
    NO_TEXT_LAYER,
    UNREADABLE_PDF,
    Content,
    ContentState,
    has_text_layer,
    pages_key,
    too_many_pages,
)
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.knowledge.domain.limits import FileLimits
from smart_tutor.knowledge.domain.upload import UploadOutcome, parse_upload_key
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore
from smart_tutor.knowledge.ports.pdf_extractor import (
    ExtractionTimeoutError,
    PdfExtractor,
    TooManyPagesError,
    UnreadablePdfError,
)
from smart_tutor.shared.domain.ids import ContentId, UploadId, UserId
from smart_tutor.shared.ports.run_tracing import NoRunTracing, RunTracing

logger = logging.getLogger(__name__)

# Derived from the upload id so a redelivery reuses the contents/ key; the worker can't delete an orphan PDF there.
CONTENT_ID_NAMESPACE = uuid.UUID("6f1c2a5e-8d3b-4e7a-9c41-2b5d7e9f0a13")


def content_id_for(upload_id: UploadId) -> ContentId:
    return ContentId(str(uuid.uuid5(CONTENT_ID_NAMESPACE, upload_id)))


@dataclass(frozen=True)
class ProcessingTools:
    """What turns a stored PDF into a description and embedded chunks; the ids are recorded on the content."""

    extractor: PdfExtractor
    describer: DocumentDescriber
    chunker: BaseDocumentTransformer
    chunker_id: str
    embeddings: Embeddings
    embedding_model: str
    embedding_dim: int
    tracing: RunTracing = field(default_factory=NoRunTracing)  # groups a content's model calls in one trace (PRD §10.4)


class IngestionService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        tools: ProcessingTools,
        limits: FileLimits,
    ) -> None:
        self._uow, self._objects, self._tools, self._limits = uow, objects, tools, limits

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
                upload = tx.uploads.get(upload_id)
                if upload is not None and upload.user_id == user_id and upload.outcome is not None:
                    # A redelivered duplicate: its placeholder document is gone; only the copy may be left.
                    logger.info("upload %s was already handled", upload_id)
                    self._objects.delete(key)
                else:
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
            # Only this learner's contents are looked up (D18, D19): another learner's copy is never found.
            content, created = tx.contents.insert_or_get(
                Content.first_upload(content_id_for(upload_id), sha256, len(data), user_id)
            )
            if created:
                self._objects.copy(key, content.s3_key)
                document.link_content(content.content_id)
                tx.documents.save(document)
                target, outcome = document.document_id, UploadOutcome.STORED
            else:
                existing = tx.documents.get_by_content(content.content_id)
                if existing is None:
                    raise LookupError(f"content {content.content_id} has no document")  # redelivered, then DLQ
                tx.documents.remove(document.document_id)  # no second document (US-11)
                target, outcome = existing.document_id, UploadOutcome.DUPLICATE
            tx.uploads.record_outcome(upload_id, len(data), outcome, target)
            tx.commit()
        self._objects.delete(key)
        logger.info("upload %s: %s", upload_id, outcome.value)
        return outcome, content.content_id if created else None

    def process_content(self, content_id: ContentId) -> ContentState | None:
        """Turn a stored content into embedded chunks and make it ready; the documents waiting on it wait for subjects.

        None when the content is missing or no longer processing (someone else finished it). Extraction and
        embedding run with no transaction open, so no lock is held across slow calls; the final transaction
        rechecks the state under lock. The first read locks the content so a retry's message waits for the
        retry to commit.
        """
        with self._uow() as tx:
            content = tx.contents.get_for_update(content_id)
        if content is None or content.state is not ContentState.PROCESSING:
            return None
        with self._tools.tracing.run("ingest", content.owner_id, {"content_id": content_id}):
            return self._process(content)

    def _process(self, content: Content) -> ContentState | None:
        content_id = content.content_id
        data = self._objects.read(content.s3_key)
        try:
            if not content.described:
                first = self._tools.extractor.extract_pages(data, self._limits.max_pages, first=FIRST_PAGES)
                self._describe(content_id, first)
            pages = self._tools.extractor.extract_pages(data, self._limits.max_pages)
        except TooManyPagesError as error:
            return self._fail(content_id, too_many_pages(error.pages, self._limits.max_pages))
        except UnreadablePdfError:
            return self._fail(content_id, UNREADABLE_PDF)
        except ExtractionTimeoutError:
            return self._fail(content_id, EXTRACTION_TIMED_OUT)
        if not has_text_layer(pages):
            return self._fail(content_id, NO_TEXT_LAYER)
        chunks = self._chunks(content_id, pages)
        if not chunks:
            return self._fail(content_id, NO_TEXT_LAYER)
        text_key = pages_key(content.owner_id, content.content_id)
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
                document.await_subjects()
                tx.documents.save(document)
            tx.commit()
        logger.info("content %s: ready with %d chunks", content_id, len(chunks))
        return ContentState.READY

    def _describe(self, content_id: ContentId, first_pages: list[str]) -> None:
        """First-pages step (PRD §9.2 step 4): store the description in its own transaction, before full extraction.

        A reply without a valid describe_document call leaves the fields empty and processing goes on; the
        document then keeps its file name as title. Model and embedding errors propagate (redelivery).
        """
        if not any(page.strip() for page in first_pages):
            return
        described = self._tools.describer.describe(first_pages)
        # Until accounts records usage, the document_processing tokens are logged.
        logger.info(
            "content %s: describe_document used %d input and %d output tokens (document_processing)",
            content_id,
            described.usage.input_tokens,
            described.usage.output_tokens,
        )
        if described.description is None:
            return
        [vector] = self._tools.embeddings.embed_documents([described.description.summary])
        if len(vector) != self._tools.embedding_dim:
            raise ValueError(
                f"The embedding model must return {self._tools.embedding_dim} floats per summary (dimension mismatch)"
            )
        with self._uow() as tx:
            locked = tx.contents.get_for_update(content_id)
            if locked is None or locked.state is not ContentState.PROCESSING or locked.described:
                return
            locked.describe(described.description, vector)
            tx.contents.save(locked)
            tx.commit()

    def _chunks(self, content_id: ContentId, pages: list[str]) -> list[Chunk]:
        """Chunk each non-blank page (keeping its physical number), check every chunk, and embed them."""
        sources = [
            TextDocument(page_content=text, metadata={"page": number})
            for number, text in enumerate(pages, start=1)
            if text.strip()
        ]
        pieces = list(self._tools.chunker.transform_documents(sources))
        found = [
            (
                validate_chunk(p.metadata.get("page"), p.page_content),
                p.page_content,
                start_index_of(p.metadata.get("start_index")),
            )
            for p in pieces
        ]
        if not found:
            return []
        vectors = self._tools.embeddings.embed_documents([text for _, text, _ in found])
        dim = self._tools.embedding_dim
        if len(vectors) != len(found) or any(len(v) != dim for v in vectors):
            raise ValueError(f"The embedding model must return {dim} floats per chunk (dimension mismatch)")
        return [
            Chunk(content_id, seq, page, text, v, start)
            for seq, ((page, text, start), v) in enumerate(zip(found, vectors, strict=True))
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
