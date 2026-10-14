"""The agent's guard (PRD §9.2, D30): the output guard, behind a question screen when `question_guard` is `bedrock`
or `guardrails_ai`. Composed here, in `apps`, because it picks adapters from settings."""

from smart_tutor.shared.adapters.aws.clients import bedrock_runtime_client, cloudwatch_client
from smart_tutor.shared.adapters.aws.cloudwatch_counter import CloudWatchCounter
from smart_tutor.shared.config import AGENT_METRICS_NAMESPACE, Settings
from smart_tutor.shared.ports.counter import Counter
from smart_tutor.tutoring.adapters.bedrock_question_screen import SCREEN_BOTO_CONFIG, BedrockQuestionScreen
from smart_tutor.tutoring.adapters.detect_jailbreak import load_detect_jailbreak
from smart_tutor.tutoring.adapters.detect_jailbreak_screen import DetectJailbreakScreen
from smart_tutor.tutoring.adapters.guardrails_guard import GuardrailsGuard
from smart_tutor.tutoring.ports.guard import Guard


def _failures(settings: Settings) -> Counter:
    return CloudWatchCounter(
        cloudwatch_client(settings),
        AGENT_METRICS_NAMESPACE,
        "QuestionScreenFailures",
        {"Deployment": settings.deployment},
    )


def build_guard(settings: Settings, prompt: str, canary: str, *, failures: Counter | None = None) -> Guard:
    guard = GuardrailsGuard(prompt, canary)
    if settings.question_guard == "off":
        return guard
    if settings.question_guard == "guardrails_ai":
        return DetectJailbreakScreen(
            guard,
            load_detect_jailbreak(settings.question_jailbreak_threshold),
            timeout=settings.question_guard_timeout_seconds,
            failures=failures or _failures(settings),
        )
    return BedrockQuestionScreen(
        guard,
        bedrock_runtime_client(settings, SCREEN_BOTO_CONFIG),
        settings.question_guardrail_id,
        settings.question_guardrail_version,
        timeout=settings.question_guard_timeout_seconds,
        failures=failures or _failures(settings),
    )
