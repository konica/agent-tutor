"""Output guard (US-6, ADR 0018): a Guardrails AI `AsyncGuard` of our own validators, fully in process.

Guardrails AI would otherwise send anonymous usage metrics to its own endpoint (on by default, re-enabled by every
`Guard()` from `~/.guardrailsrc`) and trace each validation, with the text, through the process's global OpenTelemetry
tracer provider (whatever an app or library installs there, such as Langfuse tracing in the agent). Both are off
before the first guard is built; our validators call no remote inference and nothing is installed from the hub.
"""

from typing import Any

from guardrails import AsyncGuard, OnFailAction, settings
from guardrails.utils.hub_telemetry_utils import HubTelemetry
from guardrails.validator_base import FailResult, PassResult, ValidationResult, Validator, register_validator

from smart_tutor.tutoring.domain.guard import GuardTrip
from smart_tutor.tutoring.ports.guard import Guard

LEAK_RUN = 40  # characters of the system prompt that count as a leak (the injection eval uses the same)


def _normal(text: str) -> str:
    return " ".join(text.casefold().split())


def _runs(text: str) -> set[str]:
    """Windows of `LEAK_RUN` characters that start and end with a non-space: a window edged by a space is a phrase
    boundary ("..., s"), not a quote, and would flag benign answers that share a clause with the prompt."""
    return {
        text[i : i + LEAK_RUN]
        for i in range(len(text) - LEAK_RUN + 1)
        if not text[i].isspace() and not text[i + LEAK_RUN - 1].isspace()
    }


def _in_process() -> None:
    settings.disable_tracing = True
    HubTelemetry()._tracer = None  # private, pinned by a test against the pinned version; nothing else is durable


@register_validator(name="smart-tutor/system-prompt-leak", data_type="string")
class SystemPromptLeak(Validator):
    """Fails when the text holds the prompt's canary or a run of `LEAK_RUN` characters of the prompt that starts
    and ends with a non-space, case and whitespace folded."""

    def __init__(self, prompt: str, canary: str) -> None:
        super().__init__(on_fail=OnFailAction.NOOP)  # no kwargs: the guard records them, and these are the prompt
        self._canary = canary.casefold()
        self._runs = _runs(_normal(prompt))

    def _validate(self, value: Any, metadata: dict[str, Any]) -> ValidationResult:
        text = _normal(str(value))
        if self._canary in text or not self._runs.isdisjoint(_runs(text)):
            return FailResult(error_message="system_prompt_leak")
        return PassResult()


class GuardrailsGuard(Guard):
    def __init__(self, prompt: str, canary: str) -> None:
        _in_process()
        self._guard = AsyncGuard(history_max_length=1).use(SystemPromptLeak(prompt, canary))
        self._guard.configure(allow_metrics_collection=False)

    async def check_question(self, question: str) -> GuardTrip | None:
        return None  # the Bedrock question screen (#199) is BedrockQuestionScreen, which wraps this guard; #200 is open

    async def check_answer(self, text: str) -> GuardTrip | None:
        try:
            outcome = await self._guard.validate(text)
        finally:
            self._guard.history.clear()  # keep no answer text in memory
        return None if outcome.validation_passed else GuardTrip("guard_answer", "system_prompt_leak")
