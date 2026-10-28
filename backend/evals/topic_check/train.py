"""Train the topic-check model (spec 2026-10-13 §6.2) into backend/models/topic_check.

Usage: uv run --env-file ../.env --extra eval --extra train python -m evals.topic_check.train [--dry-run]
    [--base BAAI/bge-small-en-v1.5] [--epochs 1] [--seed 42] [--out ../models/topic_check]

1. Reads the accepted topic_check candidates (the review queue and the newest full version; publishing isn't needed)
   and keeps the training share; the held-out share and the hand-written examples evaluate.
2. Holds out 15% of the training share, trains SetFit on the rest, and picks the threshold on the held-out slice
   (false rejections <= 0.5%).
3. Exports the body to ONNX (dynamic shapes), quantizes it to int8, and writes tokenizer.json, head.npz, and
   manifest.json, all in a temporary folder.
4. Checks the exported model against SetFit on the held-out slice (within 0.02) and reports false rejections and
   off-topic caught on the eval share. Exits 1 if the export drifts or the targets (<= 1%, >= 95%) are missed, and
   leaves --out untouched; only a passing model is copied there.

--dry-run prints how many on- and off-topic messages each share holds and trains nothing.
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from evals.dataset import load_dataset
from evals.langfuse_client import HINT, LangfuseClient, LangfuseError, SdkLangfuse
from evals.publish import generated_examples
from evals.topic_check.data import (
    Labeled,
    holdout,
    labeled,
    pick_threshold,
    publish_model,
    rates,
    split_train_eval,
    training_rows,
)
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier

OUT = Path(__file__).parents[2] / "models" / "topic_check"
HOLDOUT_SHARE = 0.15
MIN_TRAIN = 40  # per label
MAX_DRIFT = 0.02
TARGET_FALSE_REJECTIONS, TARGET_CAUGHT = 0.01, 0.95


def _counts(name: str, rows: Sequence[Labeled]) -> str:
    on = sum(not r.off_topic for r in rows)
    return f"{name}: {on} on-topic, {len(rows) - on} off-topic"


def _train(rows: Sequence[Labeled], base: str, epochs: int, seed: int) -> Any:
    from datasets import Dataset as HfDataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    texts, labels = training_rows(rows)
    model = SetFitModel.from_pretrained(base)
    args = TrainingArguments(num_epochs=epochs, batch_size=16, seed=seed)
    Trainer(model=model, args=args, train_dataset=HfDataset.from_dict({"text": texts, "label": labels})).train()
    if list(model.model_head.classes_) != [0, 1]:
        raise ValueError(f"expected a binary head with classes [0, 1], not {list(model.model_head.classes_)}")
    return model


def _setfit_score(model: Any, row: Labeled) -> float:
    return float(min(model.predict_proba(row.texts, as_numpy=True)[:, 1]))


def _pooling(body: Any) -> str:
    config = body[1].get_config_dict()
    pooling = config.get("pooling_mode") or (
        "cls" if config.get("pooling_mode_cls_token") else "mean" if config.get("pooling_mode_mean_tokens") else None
    )
    if pooling not in ("cls", "mean"):
        raise ValueError(f"the topic check supports cls or mean pooling, not {config}")
    return str(pooling)


def _export(model: Any, out: Path, manifest: dict[str, Any]) -> None:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    body = model.model_body
    transformer, tokenizer = body[0].auto_model, body.tokenizer
    sample = tokenizer(["a sample question"], return_tensors="pt")
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]

    class Body(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.transformer = transformer

        def forward(self, *inputs: Any) -> Any:
            return self.transformer(**dict(zip(names, inputs, strict=True))).last_hidden_state

    transformer.eval()
    with tempfile.TemporaryDirectory() as tmp:
        fp32 = Path(tmp) / "body.fp32.onnx"
        torch.onnx.export(
            Body(),
            tuple(sample[n] for n in names),
            str(fp32),
            input_names=names,
            output_names=["last_hidden_state"],
            dynamic_axes={n: {0: "batch", 1: "tokens"} for n in [*names, "last_hidden_state"]},
            opset_version=17,
            dynamo=False,
        )
        quantize_dynamic(str(fp32), str(out / "body.onnx"), weight_type=QuantType.QInt8)
    tokenizer.backend_tokenizer.save(str(out / "tokenizer.json"))
    np.savez(out / "head.npz", coef=model.model_head.coef_, intercept=model.model_head.intercept_)
    full = {
        **manifest,
        "pooling": _pooling(body),
        "normalize": any(type(m).__name__ == "Normalize" for m in body),
        "max_tokens": int(body.max_seq_length),
    }
    (out / "manifest.json").write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None, *, client: LangfuseClient | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the shares' sizes; train nothing")
    parser.add_argument("--base", default="BAAI/bge-small-en-v1.5", help="the sentence-transformer body")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    dataset = load_dataset("topic_check")
    assert dataset.eval_share is not None, "topic_check.yaml must set eval_share"
    try:
        examples = generated_examples(client or SdkLangfuse(), dataset)
    except LangfuseError as e:
        print(f"Can't reach Langfuse: {e} ({HINT})", file=sys.stderr)
        return 1
    accepted = [labeled(e) for e in examples]
    hand = [str(e.inputs["question"]) for e in dataset.examples]
    train, evaluation = split_train_eval(accepted, hand, dataset.eval_share)
    evaluation += [labeled(e) for e in dataset.examples]
    print(_counts("train", train))
    print(_counts("eval", evaluation))
    if args.dry_run:
        return 0
    if min(sum(r.off_topic for r in train), sum(not r.off_topic for r in train)) < MIN_TRAIN:
        print(f"Too few accepted messages to train: at least {MIN_TRAIN} of each label.", file=sys.stderr)
        return 1
    fit, held = holdout(train, HOLDOUT_SHARE, args.seed)
    model = _train(fit, args.base, args.epochs, args.seed)
    held_scores = [(_setfit_score(model, r), r.off_topic) for r in held]
    threshold = pick_threshold(held_scores)
    now = datetime.now(UTC)
    manifest = {
        "version": f"setfit-{args.base.rsplit('/', 1)[-1]}-int8@{now:%Y-%m-%d}",
        "base_model": args.base,
        "threshold": threshold,
        "trained_on": {"dataset": dataset.name, "messages": len(fit), "held_out": len(held)},
        "created_at": now.isoformat(timespec="seconds"),
    }
    # Export and check in a temporary folder; --out changes only when the model passes both checks.
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        staged = Path(tmp)
        _export(model, staged, manifest)
        exported = OnnxSetFitTopicClassifier(staged)
        drift = max(abs(min(exported.p_off_topic(r.texts)) - p) for r, (p, _) in zip(held, held_scores, strict=True))
        rejected, caught = rates([(min(exported.p_off_topic(r.texts)), r.off_topic) for r in evaluation], threshold)
        print(f"{manifest['version']}: threshold {threshold:.2f}, export drift {drift:.4f}")
        print(f"eval share: false rejections {rejected:.2%} (<= 1%), off-topic caught {caught:.2%} (>= 95%)")
        if drift > MAX_DRIFT:
            print(f"The int8 export drifts {drift:.3f} from SetFit (> {MAX_DRIFT}).", file=sys.stderr)
            return 1
        if rejected > TARGET_FALSE_REJECTIONS or caught < TARGET_CAUGHT:
            print("The model misses the topic_check targets: review more data or try another --base.", file=sys.stderr)
            return 1
        del exported  # release the model files before they are copied and the folder is removed
        publish_model(staged, args.out)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
