"""Give existing chunks their `start_index` by locating their text in the saved page text (PRD §9.4).

Chunk ids and texts stay as they are, so citations keep working. The worker runs it at startup; it only reads
contents that still have a chunk without an offset, so after the first run it is cheap. A chunk whose text can't be
located stays null and is logged (the viewer then shows its page without a highlight).
"""

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from smart_tutor.knowledge.domain.chunk import StoredChunk
from smart_tutor.knowledge.domain.page_text import clean_page_text, locate_chunks
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore
from smart_tutor.shared.domain.ids import ContentId

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    located: int
    missing: int


class StartIndexBackfill:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore) -> None:
        self._uow, self._objects = uow, objects

    def run(self) -> BackfillResult:
        with self._uow() as tx:
            content_ids = tx.chunks.contents_missing_start_index()
        located = missing = 0
        for content_id in content_ids:
            try:
                found, lost = self._content(content_id)
            except Exception:
                # One bad content must not stop the worker from starting. It isn't counted as missing: we may not
                # have listed its chunks yet.
                logger.exception("content %s: start_index backfill failed; its chunks keep no start_index", content_id)
                continue
            located, missing = located + found, missing + lost
        return BackfillResult(located, missing)

    def _content(self, content_id: ContentId) -> tuple[int, int]:
        with self._uow() as tx:
            content = tx.contents.get(content_id)
            chunks = [c for c in tx.chunks.list_for_content(content_id) if c.start_index is None]
        pages = self._pages(content.text_key) if content is not None and content.text_key else None
        if pages is None:
            logger.warning("content %s: no saved page text; %d chunks keep no start_index", content_id, len(chunks))
            return 0, len(chunks)
        by_page: dict[int | None, list[StoredChunk]] = defaultdict(list)
        for chunk in chunks:
            by_page[chunk.page].append(chunk)
        offsets: dict[str, int] = {}
        for page, on_page in by_page.items():
            text = pages.get(page) if page is not None else None
            starts = locate_chunks(clean_page_text(text), [c.text for c in on_page]) if text is not None else []
            for chunk, start in zip(on_page, starts or [None] * len(on_page), strict=True):
                if start is None:
                    logger.warning(
                        "chunk %s of content %s: text not found on its page; start_index stays null",
                        chunk.chunk_id,
                        content_id,
                    )
                else:
                    offsets[chunk.chunk_id] = start
        with self._uow() as tx:
            tx.chunks.set_start_indexes(offsets)
            tx.commit()
        return len(offsets), len(chunks) - len(offsets)

    def _pages(self, key: str) -> dict[int, str] | None:
        try:
            listing = json.loads(self._objects.read(key))
        except ObjectNotFoundError:
            return None
        return {int(p["page"]): str(p["text"]) for p in listing["pages"]}
