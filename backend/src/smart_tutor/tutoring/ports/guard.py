"""The guards around the answer model (PRD D28): the learner's question before search, the model's answer while it
streams. Document text is quoted and checked through the answer, never blocked."""

from abc import ABC, abstractmethod

from smart_tutor.tutoring.domain.guard import GuardTrip


class Guard(ABC):
    @abstractmethod
    async def check_question(self, question: str) -> GuardTrip | None:
        """A trip when the question must not reach search or the model (a question screen, #199/#200)."""

    @abstractmethod
    async def check_answer(self, text: str) -> GuardTrip | None:
        """A trip when the answer so far (all of it, not the newest piece) must not reach the learner."""
