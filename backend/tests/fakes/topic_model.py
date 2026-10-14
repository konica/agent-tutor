"""A tiny topic-check model directory for tests (spec 2026-10-13 §5.2): a word-level tokenizer, an ONNX "body" that
looks each token up in a 2-d table (on-topic words [1, 0], off-topic words [0, 1], others [0, 0]), and a logistic head
with coef [-4, 4], so a pure on-topic text scores sigmoid(-4) ≈ 0.018 and a pure off-topic one sigmoid(4) ≈ 0.982."""

import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from tokenizers import Tokenizer, normalizers, pre_tokenizers
from tokenizers.models import WordLevel

VOCAB = {"[UNK]": 0, "explain": 1, "photosynthesis": 2, "derivative": 3, "tell": 4, "joke": 5, "weather": 6}
ON_WORDS, OFF_WORDS = ("explain", "photosynthesis", "derivative"), ("tell", "joke", "weather")


def _table() -> np.ndarray:
    table = np.zeros((len(VOCAB), 2), dtype=np.float32)
    for word in ON_WORDS:
        table[VOCAB[word]] = [1.0, 0.0]
    for word in OFF_WORDS:
        table[VOCAB[word]] = [0.0, 1.0]
    return table


def _write_body(path: Path) -> None:
    ids = helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "tokens"])
    out = helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, ["batch", "tokens", 2])
    gather = helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"], axis=0)
    graph = helper.make_graph([gather], "body", [ids], [out], [numpy_helper.from_array(_table(), "table")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8  # onnxruntime may not read the newest IR version
    onnx.save(model, str(path))


def write_topic_model(
    folder: Path,
    *,
    pooling: str = "mean",
    normalize: bool = True,
    threshold: float = 0.5,
    max_tokens: int = 64,
    head_rows: int = 1,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _write_body(folder / "body.onnx")
    tokenizer = Tokenizer(WordLevel(VOCAB, unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(folder / "tokenizer.json"))
    coef = np.tile(np.array([[-4.0, 4.0]], dtype=np.float32), (head_rows, 1))
    np.savez(folder / "head.npz", coef=coef, intercept=np.zeros(head_rows, dtype=np.float32))
    manifest = {
        "version": "fixture@1",
        "pooling": pooling,
        "normalize": normalize,
        "max_tokens": max_tokens,
        "threshold": threshold,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder
