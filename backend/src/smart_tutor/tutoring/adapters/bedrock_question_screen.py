"""Question screen (US-6, #199, PRD D30): the learner's question, and only it, goes to a Bedrock guardrail's
prompt-attack filter (Standard tier: jailbreak, prompt injection, prompt leakage) before search. Answers are checked by
the inner guard.

A screen that fails or is slower than `timeout` lets the question through (fail open: the code defenses and the output
guard still apply) and counts the failure without waiting for the count, so a slow metrics service never delays the
turn. The log line names only the exception's type: botocore messages can quote the request.
"""

import asyncio
import logging
from typing import Any

from botocore.config import Config

from smart_tutor.shared.ports.counter import Counter
from smart_tutor.tutoring.domain.guard import GuardTrip, Screening
from smart_tutor.tutoring.ports.guard import Guard

logger = logging.getLogger(__name__)

# One retry, short timeouts: the screen runs before the first token and fails open anyway.
SCREEN_BOTO_CONFIG = Config(connect_timeout=1, read_timeout=2, retries={"mode": "standard", "max_attempts": 2})


class BedrockQuestionScreen(Guard):
    def __init__(
        self,
        inner: Guard,
        client: Any,  # a bedrock-runtime client (typed `Any`: its stub types the call by keyword)
        guardrail_id: str,
        guardrail_version: str,
        *,
        timeout: float,
        failures: Counter,
    ) -> None:
        self._inner, self._client = inner, client
        self._id, self._version = guardrail_id, guardrail_version
        self._timeout, self._failures = timeout, failures
        self._counting: set[asyncio.Task[None]] = set()  # strong references until each count finishes

    async def screen(self, question: str) -> Screening:
        """One ApplyGuardrail call on the question; raises when it fails (evals must not read a failure as a pass)."""
        reply = await asyncio.to_thread(
            self._client.apply_guardrail,
            guardrailIdentifier=self._id,
            guardrailVersion=self._version,
            source="INPUT",
            content=[{"text": {"text": question}}],
        )
        assessments = reply.get("assessments") or [{}]
        latency = assessments[0].get("invocationMetrics", {}).get("guardrailProcessingLatency")
        return Screening(
            reply["action"] == "GUARDRAIL_INTERVENED", int(reply.get("usage", {}).get("contentPolicyUnits", 0)), latency
        )

    async def check_question(self, question: str) -> GuardTrip | None:
        try:
            found = await asyncio.wait_for(self.screen(question), self._timeout)
        except Exception as e:  # TimeoutError included
            logger.warning("question screen unavailable, letting the question through: %s", type(e).__name__)
            task = asyncio.create_task(self._failures.increment())
            self._counting.add(task)
            task.add_done_callback(self._counting.discard)
            return None
        return GuardTrip("guard_question", "prompt_attack") if found.tripped else None

    async def check_answer(self, text: str) -> GuardTrip | None:
        return await self._inner.check_answer(text)
