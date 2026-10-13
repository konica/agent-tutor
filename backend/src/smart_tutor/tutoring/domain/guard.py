"""Guard trips (PRD US-6, D28, D29): a guard that trips replaces the turn's answer with one message. Its reason is for
logs and traces only; the learner never reads about an attack."""

from dataclasses import dataclass
from typing import Literal

GUARD_MESSAGE = "I can only answer questions about your documents. Rephrase it to ask about their content."
GUARD_DECLINE = "guard"  # the decline code a tripped turn is kept with: no documents used, never sent as history

GuardReason = Literal["guard_question", "guard_answer"]


@dataclass(frozen=True)
class GuardTrip:
    reason: GuardReason
    check: str  # the check that tripped, e.g. "system_prompt_leak"; logs and traces only
