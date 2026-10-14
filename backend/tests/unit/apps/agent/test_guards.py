import pytest
from pydantic import ValidationError

from fakes import CountingCounter
from smart_tutor.apps.agent import guards
from smart_tutor.apps.agent.guards import build_guard
from smart_tutor.shared.config import Settings
from smart_tutor.tutoring.adapters.bedrock_question_screen import BedrockQuestionScreen
from smart_tutor.tutoring.adapters.detect_jailbreak import JailbreakExtraMissing
from smart_tutor.tutoring.adapters.detect_jailbreak_screen import DetectJailbreakScreen
from smart_tutor.tutoring.adapters.guardrails_guard import GuardrailsGuard


def test_off_by_default_builds_only_the_output_guard() -> None:
    assert isinstance(build_guard(Settings(_env_file=None), "prompt", "stc-x"), GuardrailsGuard)


def test_bedrock_wraps_the_output_guard_in_the_question_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    # a real boto3 client would load and cache the developer's credentials in boto3's default session
    monkeypatch.setattr(guards, "bedrock_runtime_client", lambda *args, **kwargs: object())
    monkeypatch.setattr(guards, "cloudwatch_client", lambda *args, **kwargs: object())
    settings = Settings(
        _env_file=None, question_guard="bedrock", question_guardrail_id="gr", question_guardrail_version="1"
    )
    assert isinstance(build_guard(settings, "prompt", "stc-x", failures=CountingCounter()), BedrockQuestionScreen)


@pytest.mark.parametrize("missing", [{"question_guardrail_id": ""}, {"question_guardrail_version": ""}])
def test_bedrock_without_a_guardrail_refuses_to_start(missing: dict[str, str]) -> None:
    values = {"question_guard": "bedrock", "question_guardrail_id": "gr", "question_guardrail_version": "1", **missing}
    with pytest.raises(ValidationError, match="question_guardrail"):
        Settings(_env_file=None, **values)  # type: ignore[arg-type]


def test_guardrails_ai_wraps_the_output_guard_in_the_local_screen(monkeypatch: pytest.MonkeyPatch) -> None:
    thresholds: list[float] = []
    monkeypatch.setattr(guards, "load_detect_jailbreak", lambda threshold: thresholds.append(threshold) or object())
    monkeypatch.setattr(guards, "cloudwatch_client", lambda *args, **kwargs: object())
    settings = Settings(_env_file=None, question_guard="guardrails_ai", question_jailbreak_threshold=0.9)
    assert isinstance(build_guard(settings, "prompt", "stc-x"), DetectJailbreakScreen)
    assert thresholds == [0.9]


def test_guardrails_ai_without_the_extra_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(threshold: float) -> object:
        raise JailbreakExtraMissing("build the agent-jailbreak image")

    monkeypatch.setattr(guards, "load_detect_jailbreak", missing)
    with pytest.raises(JailbreakExtraMissing, match="agent-jailbreak"):
        build_guard(Settings(_env_file=None, question_guard="guardrails_ai"), "prompt", "stc-x")


@pytest.mark.parametrize("threshold", [0.0, 1.0])
def test_the_threshold_is_strictly_between_0_and_1(threshold: float) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, question_jailbreak_threshold=threshold)
