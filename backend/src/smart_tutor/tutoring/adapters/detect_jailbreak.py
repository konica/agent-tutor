"""Guardrails AI's DetectJailbreak validator (#200), local on CPU: three Hugging Face models at pinned commits, baked
into the `agent-jailbreak` image by `fetch` and loaded with the Hub offline, so nothing is downloaded at runtime and
nothing leaves the process (no remote inference, Guardrails AI telemetry and tracing off as for the output guard).

    python -m smart_tutor.tutoring.adapters.detect_jailbreak fetch <cache_dir>   # then HF_HOME=<cache_dir>
"""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from smart_tutor.tutoring.adapters.guardrails_guard import in_process

_WEIGHTS = ("*.json", "*.txt", "model.safetensors")  # no duplicate TF, Flax, ONNX, or .bin copies
MODELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "GuardrailsAI/prompt-saturation-attack-detector": ("6e8dbe4acfa5d699a1512f07885874260e8ae4ca", _WEIGHTS),
    "google-bert/bert-base-cased": ("cd5ef92a9fb2f889e972770a36d4ed042daf221e", ("*.json", "*.txt")),  # tokenizer
    "sentence-transformers/all-MiniLM-L6-v2": ("1110a243fdf4706b3f48f1d95db1a4f5529b4d41", _WEIGHTS),
    "zhx123/ftrobertallm": ("edf8a6fa8e51a5e06b0139cc5c7d3358eeb79cf3", _WEIGHTS),
}


class JailbreakExtraMissing(RuntimeError):
    pass


def fetch_models(cache_dir: Path, *, download: Callable[..., str] | None = None) -> None:
    """Download each model at its commit into a Hugging Face cache, with `refs/main` at that commit: the validator
    asks for the repo id (revision `main`), which then resolves offline to the pinned files."""
    if download is None:
        from huggingface_hub import snapshot_download

        download = snapshot_download
    for repo, (commit, patterns) in MODELS.items():
        download(repo_id=repo, revision=commit, cache_dir=cache_dir, allow_patterns=list(patterns))
        refs = cache_dir / f"models--{repo.replace('/', '--')}" / "refs"
        refs.mkdir(parents=True, exist_ok=True)
        (refs / "main").write_text(commit)


def load_detect_jailbreak(threshold: float) -> Any:
    """The validator, loaded from the baked cache; raises at startup when the extra or a model is missing."""
    os.environ["HF_HUB_OFFLINE"] = "1"  # before transformers is imported: it reads these once
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        from guardrails import OnFailAction
        from guardrails_ai.detect_jailbreak import DetectJailbreak
        from huggingface_hub import constants as hub_constants
    except ModuleNotFoundError as e:
        raise JailbreakExtraMissing(
            "question_guard is guardrails_ai but the jailbreak extra is not installed: "
            "build the agent-jailbreak image (docker build --target agent-jailbreak)"
        ) from e
    if not hub_constants.HF_HUB_OFFLINE:
        raise RuntimeError(
            "huggingface_hub was imported before the DetectJailbreak loader, so the Hub is online and revision "
            "'main' could resolve past the pinned commits: set HF_HUB_OFFLINE=1 in the environment"
        )
    in_process()
    validator = DetectJailbreak(threshold=threshold, device="cpu", use_local=True, on_fail=OnFailAction.NOOP)
    # The first run is cold (~18 s): keep it out of a learner's 1 s.
    validator.validate("What does the paper say about attention heads?", {})
    return validator


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "fetch":
        sys.exit("usage: python -m smart_tutor.tutoring.adapters.detect_jailbreak fetch <cache_dir>")
    fetch_models(Path(sys.argv[2]) / "hub")  # HF_HOME/hub is where the Hub looks
