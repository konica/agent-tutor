"""How an evaluation run invokes the agent: one input example in, the run's outputs and trajectory out (M2)."""

from typing import Any

from evals.corpus_index import CorpusIndex, build_index, index_key, load_or_build_index
from evals.seed_corpus.manifest import PDF_DIR, load_manifest
from smart_tutor.knowledge.adapters.chunking import build_chunker
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.config import Settings


def seed_index(settings: Settings) -> CorpusIndex:
    """The seed corpus chunked and embedded as the app would, cached under `data/seed_corpus/index/`."""
    docs = load_manifest()
    missing = [d.pdf_path() for d in docs if not d.pdf_path().exists()]
    if missing:
        raise FileNotFoundError(
            f"{len(missing)} seed PDFs are missing (first: {missing[0]}); "
            "run `uv run --extra eval python -m evals.seed_corpus.download`"
        )
    chunker, chunker_id = build_chunker(settings.chunking)
    embeddings = ModelFactory(settings).embedding()
    extractor = PypdfExtractor()
    key = index_key(chunker_id, settings.models.embedding.model_id, docs)
    return load_or_build_index(
        docs,
        PDF_DIR / "index",
        key,
        lambda: build_index(docs, lambda d: d.pdf_path().read_bytes(), extractor, chunker, embeddings),
    )


def tutor_target(inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("M2: invoke the agent graph and return answer, citations, trajectory, state.subject")
