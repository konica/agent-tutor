"""Answer step (PRD §9.2): stream the model's answer over quoted chunks.

The answer streams as the node's own ``custom`` events, each piece checked by the output guard with all the text so
far; a trip ends the turn with the ``guard`` decline and nothing of the answer (US-6, D29).

Nothing readable ends in the upload request (US-3), and a search limited to given documents that doesn't cover the
question in a decline (US-4c); the model is called for neither.
"""

from collections.abc import AsyncGenerator
from contextlib import aclosing
from typing import Protocol, cast

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessageChunk
from langgraph.config import get_stream_writer

from smart_tutor.apps.agent.state import AskState
from smart_tutor.tutoring.application import Guard, answer_messages, cited_chunks, covers


class AnswerNode(Protocol):
    async def __call__(self, state: AskState) -> AskState: ...


def answer_node(model: BaseChatModel, answer_floor: float, max_tokens: int, guard: Guard, system: str) -> AnswerNode:
    capped = model.bind(max_tokens=max_tokens)  # no tools: the answer is plain text (US-6)

    async def answer(state: AskState) -> AskState:
        if state.get("no_documents"):
            return {"answer": "", "citations": [], "decline": "no_documents"}
        chunks = state.get("chunks", [])
        if state.get("document_ids") is not None and not covers(chunks, answer_floor):
            return {"answer": "", "citations": [], "decline": "limited"}
        write = get_stream_writer()
        messages = answer_messages(state["question"], chunks, state.get("history", []), system=system)
        text = ""
        stream = cast(
            "AsyncGenerator[BaseMessageChunk, None]", capped.astream(messages)
        )  # astream is an async generator
        async with aclosing(stream):  # a trip closes the model's stream at once
            async for piece in stream:
                if not piece.text:
                    continue
                text += piece.text
                if (trip := await guard.check_answer(text)) is not None:  # before the piece leaves (D29)
                    return {"answer": "", "citations": [], "decline": "guard", "guard": trip.reason}
                write({"delta": piece.text})
        return {"answer": text, "citations": [c.citation(n) for n, c in cited_chunks(text, chunks)]}

    return answer
