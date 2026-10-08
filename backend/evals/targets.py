"""How an evaluation run invokes the agent: one input example in, the run's outputs and trajectory out (M2)."""

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from evals.corpus_index import (
    CorpusIndex,
    SeedCorpusRetriever,
    build_index,
    index_key,
    load_or_build_index,
    subject_id,
)
from evals.seed_corpus.manifest import PDF_DIR, SeedDocument, load_manifest
from smart_tutor.knowledge.adapters.chunking import build_chunker
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.shared.adapters.aws.clients import ssm_client
from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.tutoring.application import load_detection_policy
from smart_tutor.tutoring.application.subject_detector import SubjectDetector
from smart_tutor.tutoring.domain.detection import DetectionPolicy


def read_verified_pdf(doc: SeedDocument, pdf_dir: Path = PDF_DIR) -> bytes:
    """The document's PDF bytes, checked against the manifest SHA-256 so a truncated file is never indexed."""
    path = doc.pdf_path(pdf_dir)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != doc.sha256:
        raise ValueError(
            f"{doc.id}: {path} does not match the manifest SHA-256 (truncated or corrupt); "
            "re-run `uv run --extra eval python -m evals.seed_corpus.download`"
        )
    return data


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
        lambda: build_index(docs, read_verified_pdf, extractor, chunker, embeddings),
    )


def ssm_policy(settings: Settings) -> DetectionPolicy:
    """The policy the agent would load (SSM; LocalStack locally)."""
    return load_detection_policy(
        SsmParameterStore(ssm_client(settings)),
        settings.detect_threshold_param,
        settings.detect_margin_param,
        settings.multi_margin_param,
    )


def parse_policy(text: str) -> DetectionPolicy:
    """`T,M,MM` as given to `--policy`."""
    parts = text.split(",")
    if len(parts) != 3:
        raise ValueError(f"--policy needs THRESHOLD,MARGIN,MULTI_MARGIN, got {text!r}")
    threshold, margin, multi_margin = (float(p) for p in parts)
    return DetectionPolicy(threshold, margin, multi_margin)


def learner_subject_names(index: CorpusIndex, learner_documents: list[str]) -> list[str]:
    return sorted({name for doc_id in learner_documents for name in index.documents[doc_id].subjects})


def detection_target(
    index: CorpusIndex, embeddings: Embeddings, policy: DetectionPolicy
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Detect a first question's subjects as the agent would, over the learner's seed documents; names, not ids."""

    def target(inputs: dict[str, Any]) -> dict[str, Any]:
        names = learner_subject_names(index, inputs["learner_documents"])
        by_id = {subject_id(n): n for n in names}
        retriever = SeedCorpusRetriever(index, inputs["learner_documents"], embeddings)
        detection = asyncio.run(SubjectDetector(retriever, policy).detect(inputs["question"], list(by_id)))
        return {
            "subjects": [by_id[s] for s in detection.subject_ids],
            "unsure": detection.unsure,
            "scores": {by_id[s]: score for s, score in detection.scores.items()},
        }

    return target


def tutor_target(inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("M2: invoke the agent graph and return answer, citations, trajectory, state.subject")
