import builtins
import os
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from guardrails import OnFailAction

from smart_tutor.tutoring.adapters.detect_jailbreak import (
    MODELS,
    JailbreakExtraMissing,
    fetch_models,
    load_detect_jailbreak,
)


def test_every_model_is_pinned_to_a_full_commit() -> None:
    assert set(MODELS) == {
        "GuardrailsAI/prompt-saturation-attack-detector",
        "google-bert/bert-base-cased",
        "sentence-transformers/all-MiniLM-L6-v2",
        "zhx123/ftrobertallm",
    }
    assert all(len(commit) == 40 for commit, _ in MODELS.values())


def test_fetch_downloads_each_pinned_commit_and_points_main_at_it(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def download(**kwargs: Any) -> str:
        calls.append(kwargs)
        return str(tmp_path)

    fetch_models(tmp_path, download=download)
    assert {(c["repo_id"], c["revision"]) for c in calls} == {(repo, commit) for repo, (commit, _) in MODELS.items()}
    assert all(c["cache_dir"] == tmp_path for c in calls)
    commit, _ = MODELS["zhx123/ftrobertallm"]
    assert (tmp_path / "models--zhx123--ftrobertallm" / "refs" / "main").read_text() == commit


def test_loading_without_the_extra_names_the_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    real_import = builtins.__import__

    def no_extra(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("guardrails_ai"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_extra)
    with pytest.raises(JailbreakExtraMissing, match="agent-jailbreak"):
        load_detect_jailbreak(0.81)


def test_loading_forces_the_hub_offline_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    seen: dict[str, str | None] = {}
    real_import = builtins.__import__

    def record(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("guardrails_ai"):
            seen.update(hub=os.environ.get("HF_HUB_OFFLINE"), transformers=os.environ.get("TRANSFORMERS_OFFLINE"))
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", record)
    with pytest.raises(JailbreakExtraMissing):
        load_detect_jailbreak(0.81)
    assert seen == {"hub": "1", "transformers": "1"}


def _fake_hub(monkeypatch: pytest.MonkeyPatch, *, offline: bool) -> None:
    hub = types.ModuleType("huggingface_hub")
    constants = types.ModuleType("huggingface_hub.constants")
    constants.HF_HUB_OFFLINE = offline  # type: ignore[attr-defined]
    hub.constants = constants  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)


def test_loading_warms_the_validator_with_one_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    built: list[dict[str, Any]] = []
    validated: list[str] = []

    class FakeDetectJailbreak:
        def __init__(self, **kwargs: Any) -> None:
            built.append(kwargs)

        def validate(self, value: str, metadata: dict[str, Any]) -> None:
            validated.append(value)

    parent = types.ModuleType("guardrails_ai")
    child = types.ModuleType("guardrails_ai.detect_jailbreak")
    child.DetectJailbreak = FakeDetectJailbreak  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "guardrails_ai", parent)
    monkeypatch.setitem(sys.modules, "guardrails_ai.detect_jailbreak", child)
    _fake_hub(monkeypatch, offline=True)

    validator = load_detect_jailbreak(0.7)

    assert isinstance(validator, FakeDetectJailbreak)
    assert built == [{"threshold": 0.7, "device": "cpu", "use_local": True, "on_fail": OnFailAction.NOOP}]
    assert len(validated) == 1


def test_loading_refuses_a_hub_that_was_imported_online(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    parent = types.ModuleType("guardrails_ai")
    child = types.ModuleType("guardrails_ai.detect_jailbreak")
    child.DetectJailbreak = object  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "guardrails_ai", parent)
    monkeypatch.setitem(sys.modules, "guardrails_ai.detect_jailbreak", child)
    _fake_hub(monkeypatch, offline=False)

    with pytest.raises(RuntimeError, match="HF_HUB_OFFLINE=1"):
        load_detect_jailbreak(0.7)
