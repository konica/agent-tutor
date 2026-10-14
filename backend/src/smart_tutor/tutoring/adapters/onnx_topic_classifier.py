"""TopicClassifier on a SetFit model exported to ONNX (spec 2026-10-13 §5.2, ADR 0020): onnxruntime, tokenizers, and
numpy, no torch. The model directory, made by `python -m evals.topic_check.train`, holds body.onnx (the
sentence-transformer body), tokenizer.json, head.npz (the logistic head: `coef` (1, dim), `intercept` (1,)), and
manifest.json (version, pooling, normalize, max_tokens, threshold)."""

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from smart_tutor.tutoring.domain.topic import TopicVerdict, previous_question, topic_texts
from smart_tutor.tutoring.domain.turn import HistoryTurn
from smart_tutor.tutoring.ports.topic_classifier import TopicClassifier

THREADS = 2  # the on-premise host has 2 vCPU for the whole stack (ADR 0012)


@dataclass(frozen=True)
class Manifest:
    version: str
    pooling: Literal["cls", "mean"]
    normalize: bool
    max_tokens: int
    threshold: float

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        pooling = raw["pooling"]
        if pooling not in ("cls", "mean"):
            raise ValueError(f"{path}: pooling must be cls or mean, not {pooling!r}")
        return cls(
            str(raw["version"]), pooling, bool(raw["normalize"]), int(raw["max_tokens"]), float(raw["threshold"])
        )


class OnnxSetFitTopicClassifier(TopicClassifier):
    def __init__(self, model_dir: Path) -> None:
        self._manifest = Manifest.read(model_dir / "manifest.json")
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = THREADS, 1
        self._session: Any = ort.InferenceSession(
            str(model_dir / "body.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.no_padding()
        self._tokenizer.enable_truncation(self._manifest.max_tokens)
        head = np.load(model_dir / "head.npz")
        self._coef, self._intercept = head["coef"].astype(np.float32), head["intercept"].astype(np.float32)
        if self._coef.shape[0] != 1 or self._intercept.shape != (1,):
            raise ValueError(
                f"{model_dir / 'head.npz'}: a binary logistic head has coef (1, dim) and intercept (1,), "
                f"not {self._coef.shape} and {self._intercept.shape}"
            )

    @property
    def default_threshold(self) -> float:
        return self._manifest.threshold

    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict:
        texts = topic_texts(question, previous_question(history))
        scores = await asyncio.to_thread(self.p_off_topic, texts)
        return TopicVerdict(min(scores), self._manifest.version)

    def p_off_topic(self, texts: Sequence[str]) -> list[float]:
        """P(off-topic) of each text, one at a time (no padding)."""
        return [self._score(text) for text in texts]

    def _score(self, text: str) -> float:
        encoding = self._tokenizer.encode(text)
        ids = np.array([encoding.ids], dtype=np.int64)
        mask = np.array([encoding.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        hidden = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0]  # (1, tokens, dim)
        if self._manifest.pooling == "cls":
            vector = hidden[:, 0]
        else:
            weights = mask[..., None].astype(np.float32)
            vector = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        if self._manifest.normalize:
            vector = vector / np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-12)
        logit = float((vector @ self._coef.T + self._intercept)[0, 0])
        return 1 / (1 + math.exp(-logit))
