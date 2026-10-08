"""Thread routes (tutoring module): ask the first question of a new thread; the agent detects its subjects, then the
API starts it, or the agent is unsure and the learner picks. Answered as SSE (PRD §9.2)."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from smart_tutor.apps.api.agent_client import AgentAnswer, AgentConflictError, AgentUnavailableError
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal, Subjects
from smart_tutor.apps.api.routes.knowledge import SubjectResponse
from smart_tutor.apps.api.routes.subjects import UNNAMED_SUBJECT
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.subjects.application import SubjectNames
from smart_tutor.tutoring.application import (
    MAX_SUBJECTS,
    ConversationService,
    NoDocumentsError,
    ThreadNotFoundError,
    ThreadNotPendingError,
    ThreadSubjectsError,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tutoring"])

UNAVAILABLE = "The tutor is unavailable. Try again in a moment."
# Proxies must pass each event on as it comes, and nothing may cache the answer.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
SSE_RESPONSE: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-sent events: thread, then delta*, citations, done (or error). "
        "A new thread may instead open with choose_subjects, then done.",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    409: {"description": "The learner has no ready documents."},
}
RESUME_RESPONSE: dict[int | str, dict[str, object]] = {
    200: {
        "description": "Server-sent events: thread, then delta*, citations, done (or error).",
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    404: {"description": "No such conversation."},
    409: {"description": "The conversation already has its subjects, or the tutor has no question waiting."},
    422: {"description": "The pick is not 1 to 3 distinct subjects of the learner's own."},
}


class AskRequest(BaseModel):
    # No user id: the thread's owner comes from the token (PRD §9.3). Unknown fields are refused.
    model_config = ConfigDict(extra="forbid")
    # Stripped before the length check, so a blank question is a 422; the agent gets the stripped text.
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class ChooseSubjectsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject_ids: Annotated[list[str], Field(min_length=1, max_length=MAX_SUBJECTS)]


class ThreadResponse(BaseModel):
    thread_id: str
    question: str  # the thread's title: its first question
    subjects: list[SubjectResponse]
    awaiting_subjects: bool


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


_EVENT_END = b"\n\n"
_UNAVAILABLE_EVENT = _sse("error", {"code": "unavailable", "message": UNAVAILABLE})

# Starts the thread with the detected subject ids; its `thread` event, or None when they are refused.
StartThread = Callable[[list[str]], Awaitable[bytes | None]]
# Stores a pending thread for the agent's choices; its `choose_subjects` event, or None when it can't.
StorePending = Callable[[list[str]], Awaitable[bytes | None]]


class _EndedInsideEventError(Exception):
    """The agent's stream ended part-way through an event."""


def _event(raw: bytes) -> tuple[str, object] | None:
    """(name, data) of one SSE event; None when it isn't one."""
    fields = dict(line.split(": ", 1) for line in raw.decode(errors="replace").splitlines() if ": " in line)
    try:
        return fields["event"], json.loads(fields["data"])
    except (KeyError, ValueError):
        return None


def _ids(event: tuple[str, object] | None, name: str) -> list[str] | None:
    """The ids of a well-formed `subjects` or `choose_subjects` event; None for any other event."""
    if event is None or event[0] != name or not isinstance(event[1], dict):
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


async def _opening(first: bytes | None, start: StartThread, pending: StorePending | None) -> bytes | None:
    """What replaces the agent's first event: an `error` as-is; `subjects` by the thread event; `choose_subjects` (only
    when `pending` is given) by its named version; else None."""
    if first is None:
        logger.warning("the agent's stream ended before its subjects")
        return None
    event = _event(first)
    if event is not None and event[0] == "error":
        return first
    subject_ids = _ids(event, "subjects")
    if subject_ids is not None:
        return await start(subject_ids)
    choices = _ids(event, "choose_subjects")
    if pending is not None and choices is not None:
        return await pending(choices)
    logger.warning("the agent's stream did not start with its subjects (got %s)", event[0] if event else None)
    return None


async def _relay(answer: AgentAnswer, start: StartThread, pending: StorePending | None = None) -> AsyncIterator[bytes]:
    """The agent's events, its first `subjects` (or `choose_subjects`) event replaced, forwarded only once complete.

    The thread is started only when the agent has detected its subjects; an `error` first is relayed as-is and starts
    none. If the stream drops inside an event, the partial event is dropped so the error event that follows stays a
    well-formed event of its own.
    """
    events = _events(answer)
    try:
        opening = await _opening(await anext(events, None), start, pending)
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


async def _named_subjects(
    conversations: ConversationService, subjects: SubjectNames, user_id: UserId
) -> dict[str, str]:
    """The learner's subjects (id → name, in id order), a placeholder for any without a name."""
    learner_subjects = await run_in_threadpool(conversations.subjects_for_new_thread, user_id)
    names = await run_in_threadpool(subjects.names_for, user_id, learner_subjects)
    named: dict[str, str] = {}
    for s in learner_subjects:
        if not names.get(s):
            logger.warning("subject %s has no name; using a placeholder", s)
        named[s] = names.get(s) or UNNAMED_SUBJECT
    return named


def _unauthenticated() -> HTTPException:
    return HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def _named_list(subject_ids: list[str] | tuple[str, ...], named: dict[str, str]) -> list[dict[str, str]]:
    return [{"subject_id": s, "name": named.get(s, UNNAMED_SUBJECT)} for s in subject_ids]


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
        named = await _named_subjects(conversations, subjects, principal.user_id)
    except NoDocumentsError as e:
        raise HTTPException(409, str(e)) from None
    thread_id = ThreadId(str(uuid.uuid4()))
    try:
        answer = await agent.open_answer(token, thread_id, body.question, list(named.items()))
    except UnauthenticatedError:
        raise _unauthenticated() from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None

    async def start(subject_ids: list[str]) -> bytes | None:
        try:
            thread = await run_in_threadpool(
                conversations.start_thread,
                principal.user_id,
                [SubjectId(s) for s in subject_ids],
                thread_id,
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
        return _sse("thread", {"thread_id": thread.thread_id, "subjects": _named_list(thread.subject_ids, named)})

    async def pending(choice_ids: list[str]) -> bytes | None:
        choices = [s for s in choice_ids if s in named]
        if len(choices) != len(choice_ids):
            logger.warning("the agent's choices %s include subjects the learner doesn't have", choice_ids)
        if not choices:
            return None
        try:
            await run_in_threadpool(conversations.start_pending_thread, principal.user_id, thread_id, body.question)
        except Exception:
            logger.exception("storing a pending thread failed")
            return None
        return _sse(
            "choose_subjects",
            {"thread_id": thread_id, "question": body.question, "subjects": _named_list(choices, named)},
        )

    return StreamingResponse(_relay(answer, start, pending), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post(
    "/threads/{thread_id}/subjects",
    operation_id="choose_thread_subjects",
    response_class=StreamingResponse,
    responses=RESUME_RESPONSE,
)
async def choose_thread_subjects(
    thread_id: str,
    body: ChooseSubjectsRequest,
    principal: CurrentPrincipal,
    token: BearerToken,
    conversations: Conversations,
    subjects: Subjects,
    agent: Agent,
) -> StreamingResponse:
    """The learner's pick for a thread waiting for its subjects; the agent then answers the first question."""
    picked = [SubjectId(s) for s in body.subject_ids]
    try:
        await run_in_threadpool(conversations.pending_thread, principal.user_id, ThreadId(thread_id))
        await run_in_threadpool(conversations.check_choice, principal.user_id, picked)
    except ThreadNotFoundError:
        raise HTTPException(404, "No such conversation") from None
    except ThreadNotPendingError as e:
        raise HTTPException(409, str(e)) from None
    except ThreadSubjectsError as e:
        raise HTTPException(422, str(e)) from None
    try:
        named = await _named_subjects(conversations, subjects, principal.user_id)
        answer = await agent.resume_answer(token, thread_id, body.subject_ids)
    except NoDocumentsError as e:
        raise HTTPException(409, str(e)) from None
    except UnauthenticatedError:
        raise _unauthenticated() from None
    except AgentConflictError as e:
        raise HTTPException(409, str(e)) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None

    async def bind(subject_ids: list[str]) -> bytes | None:
        if subject_ids != body.subject_ids:
            logger.warning("the agent resumed thread %s with %s, not the pick %s", thread_id, subject_ids, picked)
            return None
        try:
            bound = await run_in_threadpool(conversations.bind_subjects, principal.user_id, ThreadId(thread_id), picked)
        except Exception:
            logger.exception("binding the subjects of thread %s failed", thread_id)
            return None
        if not bound:
            logger.warning("thread %s was bound by someone else first", thread_id)
            return None
        return _sse("thread", {"thread_id": thread_id, "subjects": _named_list(subject_ids, named)})

    return StreamingResponse(_relay(answer, bind), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/threads/{thread_id}", operation_id="get_thread")
async def get_thread(
    thread_id: str, principal: CurrentPrincipal, conversations: Conversations, subjects: Subjects
) -> ThreadResponse:
    try:
        thread = await run_in_threadpool(conversations.get_thread, principal.user_id, ThreadId(thread_id))
    except ThreadNotFoundError:
        raise HTTPException(404, "No such conversation") from None
    names = await run_in_threadpool(subjects.names_for, principal.user_id, list(thread.subject_ids))
    return ThreadResponse(
        thread_id=thread.thread_id,
        question=thread.title or "",
        subjects=[SubjectResponse(subject_id=s, name=names.get(s) or UNNAMED_SUBJECT) for s in thread.subject_ids],
        awaiting_subjects=thread.awaiting_subjects,
    )
