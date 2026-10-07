"""Make a ready document with embedded chunks, for tests of search and everything built on it."""

import hashlib
from collections.abc import Sequence

from fakes.clock import FixedClock
from fakes.knowledge import FakeObjectStore, InMemoryLibrary
from fakes.models import fake_embeddings
from fakes.parameters import TEST_LIMITS
from smart_tutor.knowledge.application import UploadService
from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID


def ingest_ready(
    library: InMemoryLibrary, owner: str, text: str, subject_ids: Sequence[SubjectId] = (GENERAL_SUBJECT_ID,)
) -> DocumentId:
    """A document of `owner` that is ready in `subject_ids` (General by default), with one page-1 chunk of `text`
    embedded by `fake_embeddings()`.

    Built through the domain (not `IngestionService`) because ingestion rejects pages too short to be a text layer.
    """
    sha = hashlib.sha256(text.encode()).hexdigest()
    started = UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(
        UserId(owner), f"{sha[:8]}.pdf"
    )
    with library.unit_of_work() as tx:
        content, created = tx.contents.insert_or_get(
            Content.first_upload(ContentId(sha[:32]), sha, len(text), UserId(owner))
        )
        if created:  # an identical file of another learner is already processed: share its chunks
            content.ready(
                pages=1, text_key=f"contents/{sha}.pages.json", chunker="fake", embedding_model="fake", embedding_dim=8
            )
            tx.contents.save(content)
            tx.chunks.replace(
                content.content_id, [Chunk(content.content_id, 0, 1, text, fake_embeddings().embed_query(text))]
            )
        document = tx.documents.get_by_upload_for_update(started.upload_id)
        assert document is not None
        document.link_content(content.content_id)
        document.await_subjects()
        document.choose_subjects(list(subject_ids))
        tx.documents.save(document)
        tx.commit()
    return started.document_id
