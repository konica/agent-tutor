"""Thread routes (tutoring module): ask the first question of a new thread; the agent detects its subjects, then the
API starts it. Answered as SSE (PRD §9.2)."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

from smart_tutor.apps.api.agent_client import AgentAnswer, AgentUnavailableError
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal, Subjects
from smart_tutor.apps.api.routes.subjects import UNNAMED_SUBJECT
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import SubjectId, ThreadId
from smart_tutor.tutoring.application import NoDocumentsError, ThreadSubjectsError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tutoring"])

UNAVAILABLE = "The tutor is unavailable. Try again in a moment."
# Proxies must pass each event on as it comes, and nothing may cache the answer.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
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
    # Stripped before the length check, so a blank question is a 422; the agent gets the stripped text.
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


_EVENT_END = b"\n\n"
_UNAVAILABLE_EVENT = _sse("error", {"code": "unavailable", "message": UNAVAILABLE})

# Starts the thread with the detected subject ids; its `thread` event, or None when they are refused.
StartThread = Callable[[list[str]], Awaitable[bytes | None]]


class _EndedInsideEventError(Exception):
    """The agent's stream ended part-way through an event."""


def _event(raw: bytes) -> tuple[str, object] | None:
    """(name, data) of one SSE event; None when it isn't one."""
    fields = dict(line.split(": ", 1) for line in raw.decode(errors="replace").splitlines() if ": " in line)
    try:
        return fields["event"], json.loads(fields["data"])
    except (KeyError, ValueError):
        return None


def _subject_ids(event: tuple[str, object] | None) -> list[str] | None:
    """The ids of a well-formed `subjects` event; None for any other event."""
    if event is None or event[0] != "subjects" or not isinstance(event[1], dict):
        return None
    ids = event[1].get("subject_ids")
    if not isinstance(ids, list) or not all(isinstance(s, str) for s in ids):
        return None
    return ids


async def _events(answer: AgentAnswer) -> AsyncGenerator[bytes, None]:
    """The agent's events one by one, each with its blank line, byte-identical; network reads can end anywhere."""
    pending = b""
    async for chunk in answer.chunks():
        pending += chunk
        *complete, pending = pending.split(_EVENT_END)
        for event in complete:
            yield event + _EVENT_END
    if pending.strip():
        raise _EndedInsideEventError


async def _opening(first: bytes | None, start: StartThread) -> bytes | None:
    """What replaces the agent's first event: an `error` as-is, `subjects` by the thread event; else None."""
    if first is None:
        logger.warning("the agent's stream ended before its subjects")
        return None
    event = _event(first)
    if event is not None and event[0] == "error":
        return first
    subject_ids = _subject_ids(event)
    if subject_ids is None:
        logger.warning("the agent's stream did not start with its subjects (got %s)", event[0] if event else None)
        return None
    return await start(subject_ids)


async def _relay(answer: AgentAnswer, start: StartThread) -> AsyncIterator[bytes]:
    """The agent's events, its first `subjects` event replaced by the `thread` event, forwarded only once complete.

    The thread is started only when the agent has detected its subjects; an `error` first is relayed as-is and starts
    none. If the stream drops inside an event, the partial event is dropped so the error event that follows stays a
    well-formed event of its own.
    """
    events = _events(answer)
    try:
        opening = await _opening(await anext(events, None), start)
        if opening is None:
            yield _UNAVAILABLE_EVENT
            return
        yield opening
        async for event in events:
            yield event
    except (httpx.HTTPError, _EndedInsideEventError):
        yield _UNAVAILABLE_EVENT
    finally:
        await events.aclose()
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
        learner_subjects = await run_in_threadpool(conversations.subjects_for_new_thread, principal.user_id)
    except NoDocumentsError as e:
        raise HTTPException(409, str(e)) from None
    names = await run_in_threadpool(subjects.names_for, principal.user_id, learner_subjects)
    named: dict[str, str] = {}
    for s in learner_subjects:
        if not names.get(s):
            logger.warning("subject %s has no name; using a placeholder", s)
        named[s] = names.get(s) or UNNAMED_SUBJECT
    try:
        answer = await agent.open_answer(token, body.question, list(named.items()))
    except UnauthenticatedError:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None

    async def start(subject_ids: list[str]) -> bytes | None:
        try:
            thread = await run_in_threadpool(
                conversations.start_thread,
                principal.user_id,
                [SubjectId(s) for s in subject_ids],
                ThreadId(str(uuid.uuid4())),
                body.question,
            )
        except (ThreadSubjectsError, NoDocumentsError) as e:
            # Ids and the reason only: never the question or the token.
            logger.warning("the agent's subjects %s were refused: %s", subject_ids, e)
            return None
        except Exception:
            # The 200 headers are already sent: end the stream with an error event rather than cut it off.
            logger.exception("starting a thread with subjects %s failed", subject_ids)
            return None
        return _sse(
            "thread",
            {
                "thread_id": thread.thread_id,
                "subjects": [{"subject_id": s, "name": named.get(s, UNNAMED_SUBJECT)} for s in thread.subject_ids],
            },
        )

    return StreamingResponse(_relay(answer, start), media_type="text/event-stream", headers=SSE_HEADERS)
