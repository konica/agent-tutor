"""Answer step (PRD §9.2 step 5): stream the model's answer over quoted chunks; no chunks → fixed reply.

A search limited to given documents that doesn't cover the question ends in a decline instead (US-4c).
"""

from typing import Protocol

from langchain_core.language_models import BaseChatModel

from smart_tutor.apps.agent.state import AskState
from smart_tutor.tutoring.application import NO_CHUNKS_ANSWER, answer_messages, cited_chunks, covers


class AnswerNode(Protocol):
    async def __call__(self, state: AskState) -> AskState: ...


def answer_node(model: BaseChatModel, answer_floor: float) -> AnswerNode:
    async def answer(state: AskState) -> AskState:
        chunks = state.get("chunks", [])
        if state.get("document_ids") is not None and not covers(chunks, answer_floor):
            return {"answer": "", "citations": [], "declined": True}  # the model is never called
        if not chunks:
            return {"answer": NO_CHUNKS_ANSWER, "citations": []}
        reply = await model.ainvoke(answer_messages(state["question"], chunks))
        text = reply.text
        return {"answer": text, "citations": [c.citation(n) for n, c in cited_chunks(text, chunks)]}

    return answer
