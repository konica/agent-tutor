"""Question screen (US-6, #200, PRD D30): the learner's question, and only it, through Guardrails AI's DetectJailbreak
validator on CPU in this process, before search. Answers are checked by the inner guard.

Like the Bedrock screen (ADR 0019) it fails open: an error or a run longer than `timeout` lets the question through and
counts the failure. Runs are serialized (two would only share the same CPU cores), and a run that timed out keeps the
lock until it ends. The validator's failure message quotes the question, so it is never logged; neither is an
exception's message.
"""

import asyncio
import logging
import time
from typing import Any

from smart_tutor.shared.ports.counter import Counter
from smart_tutor.tutoring.domain.guard import GuardTrip, Screening
from smart_tutor.tutoring.ports.guard import Guard

logger = logging.getLogger(__name__)


class DetectJailbreakScreen(Guard):
    def __init__(self, inner: Guard, validator: Any, *, timeout: float, failures: Counter) -> None:
        self._inner, self._validator = inner, validator  # a DetectJailbreak (untyped: the extra is optional)
        self._timeout, self._failures = timeout, failures
        self._lock = asyncio.Lock()
        self._counting: set[asyncio.Task[None]] = set()  # strong references until each count finishes

    def _run(self, question: str) -> Screening:
        started = time.perf_counter()
        outcome = self._validator.validate(question, {}).outcome
        return Screening(outcome == "fail", 0, round((time.perf_counter() - started) * 1000))

    async def screen(self, question: str) -> Screening:
        """One validator run on the question; raises when it fails (evals must not read a failure as a pass)."""
        await self._lock.acquire()
        run = asyncio.ensure_future(asyncio.to_thread(self._run, question))
        run.add_done_callback(lambda _: self._lock.release())  # held until the thread ends, even after a timeout
        return await asyncio.shield(run)

    async def check_question(self, question: str) -> GuardTrip | None:
        try:
            found = await asyncio.wait_for(self.screen(question), self._timeout)
        except Exception as e:  # TimeoutError included
            logger.warning("question screen unavailable, letting the question through: %s", type(e).__name__)
            task = asyncio.create_task(self._failures.increment())
            self._counting.add(task)
            task.add_done_callback(self._counting.discard)
            return None
        return GuardTrip("guard_question", "jailbreak") if found.tripped else None

    async def check_answer(self, text: str) -> GuardTrip | None:
        return await self._inner.check_answer(text)
