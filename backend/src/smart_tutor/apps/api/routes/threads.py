"""Thread routes (tutoring module): ask the first question of a new thread, answered as SSE (PRD §9.2)."""

import json
from collections.abc import AsyncIterator

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.api.agent_client import AgentAnswer, AgentUnavailableError
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal, Subjects
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.tutoring.application import DetectionUnavailableError, NoDocumentsError

router = APIRouter(tags=["tutoring"])

UNAVAILABLE = "The tutor is unavailable. Try again in a moment."
SSE_RESPONSE: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-sent events: thread, then delta*, citations, done (or error).",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    409: {"description": "The learner has no ready documents."},
}


class AskRequest(BaseModel):
    # No user id: the thread's owner comes from the token (PRD §9.3). Unknown fields are refused.
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _relay(first: bytes, answer: AgentAnswer) -> AsyncIterator[bytes]:
    yield first
    try:
        async for chunk in answer.chunks():
            yield chunk
    except httpx.HTTPError:
        yield _sse("error", {"code": "unavailable", "message": UNAVAILABLE})
    finally:
        await answer.aclose()


@router.post("/threads", operation_id="ask_in_new_thread", response_class=StreamingResponse, responses=SSE_RESPONSE)
async def ask_in_new_thread(
    body: AskRequest,
    principal: CurrentPrincipal,
    token: BearerToken,
    conversations: Conversations,
    subjects: Subjects,
    agent: Agent,
) -> StreamingResponse:
    try:
        thread = await run_in_threadpool(conversations.start_thread, principal.user_id)
    except (NoDocumentsError, DetectionUnavailableError) as e:
        raise HTTPException(409, str(e)) from None
    names = await run_in_threadpool(subjects.names_for, principal.user_id, thread.subject_ids)
    named: list[tuple[str, str]] = [(s, names.get(s, "")) for s in thread.subject_ids]
    try:
        answer = await agent.open_answer(token, body.question, named)
    except UnauthenticatedError:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None
    first = _sse(
        "thread", {"thread_id": thread.thread_id, "subjects": [{"subject_id": s, "name": n} for s, n in named]}
    )
    return StreamingResponse(_relay(first, answer), media_type="text/event-stream")
