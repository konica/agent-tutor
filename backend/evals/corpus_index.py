"""Seed corpus index and an in-process retriever for the subject-detection eval.

Detection quality depends on the embeddings, the chunker, and the policy, not on the MCP transport or `can_read`,
so the eval searches an in-memory index with exact cosine similarity instead of the Compose stack.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from langchain_core.documents import BaseDocumentTransformer, Document
from langchain_core.embeddings import Embeddings

from evals.seed_corpus.manifest import SeedDocument
from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.ports.retriever import Retriever

SEED_NAMESPACE = uuid.UUID("6f1c7d1e-5b7a-4d0e-9a39-6a3f3c2b9e10")


def subject_id(name: str) -> SubjectId:
    return SubjectId(str(uuid.uuid5(SEED_NAMESPACE, name)))


@dataclass(frozen=True)
class IndexedChunk:
    chunk_id: str
    document_id: str
    page: int
    text: str


@dataclass
class CorpusIndex:
    documents: dict[str, SeedDocument]
    chunks: list[IndexedChunk]
    vectors: np.ndarray  # one L2-normalized row per chunk, aligned with `chunks`


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


def build_index(
    docs: Sequence[SeedDocument],
    read_pdf: Callable[[SeedDocument], bytes],
    extractor: PdfExtractor,
    chunker: BaseDocumentTransformer,
    embeddings: Embeddings,
    max_pages: int = 500,
) -> CorpusIndex:
    def index_one(doc: SeedDocument) -> tuple[list[IndexedChunk], np.ndarray]:
        pages = extractor.extract_pages(read_pdf(doc), max_pages)
        pieces = chunker.transform_documents(
            [Document(page_content=text, metadata={"page": n}) for n, text in enumerate(pages, start=1)]
        )
        chunks = [
            IndexedChunk(f"{doc.id}:{i}", doc.id, int(piece.metadata["page"]), piece.page_content)
            for i, piece in enumerate(pieces)
        ]
        if not chunks:
            return [], np.zeros((0, 0))
        return chunks, np.asarray(embeddings.embed_documents([c.text for c in chunks]), dtype=np.float64)

    with ThreadPoolExecutor(max_workers=8) as pool:
        parts = list(pool.map(index_one, docs))
    chunks = [c for part_chunks, _ in parts for c in part_chunks]
    matrices = [m for part_chunks, m in parts if part_chunks]
    vectors = _normalize(np.vstack(matrices)) if matrices else np.zeros((0, 0))
    return CorpusIndex({d.id: d for d in docs}, chunks, vectors)


def index_key(chunker_id: str, embedding_model_id: str, docs: Sequence[SeedDocument]) -> str:
    """Cache key: changes whenever the chunking, the embedding model, or any document's bytes would."""
    digest = hashlib.sha256()
    for part in (chunker_id, embedding_model_id, *(f"{d.id}={d.sha256}" for d in docs)):
        digest.update(part.encode())
        digest.update(b"\0")
    return digest.hexdigest()


def load_or_build_index(
    docs: Sequence[SeedDocument], cache_dir: Path, key: str, build: Callable[[], CorpusIndex]
) -> CorpusIndex:
    vectors_path = cache_dir / f"{key}.npz"
    chunks_path = cache_dir / f"{key}.json"
    if vectors_path.exists() and chunks_path.exists():
        with np.load(vectors_path) as data:
            vectors = data["vectors"]
        chunks = [IndexedChunk(**c) for c in json.loads(chunks_path.read_text(encoding="utf-8"))]
        return CorpusIndex({d.id: d for d in docs}, chunks, vectors)
    index = build()
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks_path.write_text(json.dumps([asdict(c) for c in index.chunks]), encoding="utf-8")
    np.savez(vectors_path, vectors=index.vectors)
    return index


class SeedCorpusRetriever(Retriever):
    """A learner's library of seed documents; searches only chunks of library documents with a requested subject."""

    def __init__(self, index: CorpusIndex, library: Sequence[str], embeddings: Embeddings) -> None:
        self._index = index
        self._library = set(library)
        self._embeddings = embeddings
        self._doc_subjects = {
            doc_id: frozenset(subject_id(name) for name in doc.subjects) for doc_id, doc in index.documents.items()
        }

    async def search(self, query: str, subject_ids: Sequence[SubjectId], k: int = 5) -> list[RetrievedChunk]:
        requested = set(subject_ids)
        rows = [
            i
            for i, chunk in enumerate(self._index.chunks)
            if chunk.document_id in self._library and requested & self._doc_subjects[chunk.document_id]
        ]
        if not rows:
            return []
        q = np.asarray(self._embeddings.embed_query(query), dtype=np.float64)
        norm = np.linalg.norm(q)
        scores = self._index.vectors[rows] @ (q / norm if norm else q)
        order = np.argsort(-scores, kind="stable")[:k]
        hits: list[RetrievedChunk] = []
        for pos in order:
            chunk = self._index.chunks[rows[int(pos)]]
            doc = self._index.documents[chunk.document_id]
            hits.append(
                RetrievedChunk(
                    chunk_id=chunk.chunk_id,
                    document_title=doc.title,
                    page=chunk.page,
                    text=chunk.text,
                    score=float(scores[int(pos)]),
                    subject_ids=tuple(sorted(requested & self._doc_subjects[chunk.document_id])),
                )
            )
        return hits
