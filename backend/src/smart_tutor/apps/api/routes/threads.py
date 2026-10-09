"""Thread routes (tutoring module): ask the first question of a new thread, or a later one in an existing thread; an
answer draws on all of the learner's ready documents, or only the thread's listed ones once the learner limits its
search scope (US-4c). Answered as SSE (PRD §9.2); the documents an answer drew on are recorded when it is done and
listed per thread; the learner adds documents to that list and removes them (US-4c). The learner can rename a thread
and set or read its search scope."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from typing import Annotated, Literal, Self

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from smart_tutor.apps.api.agent_client import AgentAnswer, AgentUnavailableError
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.application import (
    DocumentNotAvailableError,
    DocumentUsed,
    InvalidTitleError,
    NoDocumentsError,
    NoListedDocumentsError,
    SearchScope,
    Thread,
    ThreadArchivedError,
    ThreadNotFoundError,
)

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
ASK_IN_THREAD_RESPONSE: dict[int | str, dict[str, object]] = {
    **SSE_RESPONSE,
    404: {"description": "Not the caller's conversation."},
    409: {"description": "The conversation is archived, or the learner has no ready documents."},
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

# Starts the thread; its `thread` event, or None when it couldn't start.
StartThread = Callable[[], Awaitable[bytes | None]]
# Records the documents an answer drew on, in the thread that started; never raises.
RecordAnswer = Callable[[list[str]], Awaitable[None]]


class _EndedInsideEventError(Exception):
    """The agent's stream ended part-way through an event."""


def _event(raw: bytes) -> tuple[str, object] | None:
    """(name, data) of one SSE event; None when it isn't one."""
    fields = dict(line.split(": ", 1) for line in raw.decode(errors="replace").splitlines() if ": " in line)
    try:
        return fields["event"], json.loads(fields["data"])
    except (KeyError, ValueError):
        return None


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
    """What goes before the agent's first event: nothing for an `error` (relayed as-is, no thread), else the
    `thread` event; None when the stream ended before any event or the thread couldn't start."""
    if first is None:
        logger.warning("the agent's stream ended before its first event")
        return None
    event = _event(first)
    if event is not None and event[0] == "error":
        return b""
    return await start()


def _document_ids(data: object) -> list[str] | None:
    """The document ids of a `sources` event's data; None when it isn't one."""
    ids = data.get("document_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        logger.warning("the agent's sources event was malformed")
        return None
    return ids


async def _relay(answer: AgentAnswer, start: StartThread, record: RecordAnswer) -> AsyncIterator[bytes]:
    """The agent's events after a `thread` event, each forwarded only once complete.

    The thread starts on the agent's first event unless it is an `error`, which is relayed as-is and starts none. If
    the stream drops inside an event, the partial event is dropped so the error event that follows stays a
    well-formed event of its own.

    The agent's `sources` event is kept back; on `done`, if the thread started, its documents are recorded before
    `done` is forwarded. A stream that ends without `done` or `error` ends with an unavailable error event.
    """
    events = _events(answer)
    try:
        first = await anext(events, None)
        opening = await _opening(first, start)
        if opening is None or first is None:
            yield _UNAVAILABLE_EVENT
            return
        if opening:
            yield opening
        started = bool(opening)
        document_ids: list[str] | None = None
        ended = False
        event: bytes | None = first
        while event is not None:
            parsed = _event(event)
            name = parsed[0] if parsed else None
            if parsed and name == "sources":
                document_ids = _document_ids(parsed[1])
            else:
                if name == "done" and started and document_ids is not None:
                    await record(document_ids)
                ended = name in ("done", "error")
                yield event
            event = await anext(events, None)
        if not ended:
            logger.warning("the agent's stream ended without done or error")
            yield _UNAVAILABLE_EVENT
    except (httpx.HTTPError, _EndedInsideEventError):
        yield _UNAVAILABLE_EVENT
    finally:
        await events.aclose()
        await answer.aclose()


async def _open(agent: Agent, token: str, question: str, document_ids: Sequence[str] | None) -> AgentAnswer:
    try:
        return await agent.open_answer(token, question, document_ids)
    except UnauthenticatedError:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None


def _recorder(conversations: Conversations, user_id: UserId, thread_id: Callable[[], ThreadId | None]) -> RecordAnswer:
    """Records an answer's documents in the thread `thread_id()` gives (None: none started, so nothing to record)."""

    async def record(document_ids: list[str]) -> None:
        tid = thread_id()
        if tid is None:
            return
        try:
            await run_in_threadpool(conversations.record_answer, tid, user_id, [DocumentId(d) for d in document_ids])
        except Exception:
            # The learner already has the answer: log it and still end the stream with `done`.
            logger.exception("recording the documents used failed")

    return record


def _stream(answer: AgentAnswer, start: StartThread, record: RecordAnswer) -> StreamingResponse:
    return StreamingResponse(_relay(answer, start, record), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/threads", operation_id="ask_in_new_thread", response_class=StreamingResponse, responses=SSE_RESPONSE)
async def ask_in_new_thread(
    body: AskRequest,
    principal: CurrentPrincipal,
    token: BearerToken,
    conversations: Conversations,
    agent: Agent,
) -> StreamingResponse:
    try:
        await run_in_threadpool(conversations.require_documents, principal.user_id)
    except NoDocumentsError as e:
        raise HTTPException(409, str(e)) from None
    answer = await _open(agent, token, body.question, None)

    thread_id: ThreadId | None = None

    async def start() -> bytes | None:
        nonlocal thread_id
        try:
            thread = await run_in_threadpool(conversations.start_thread, principal.user_id, body.question)
        except NoDocumentsError as e:
            logger.warning("the thread was refused: %s", e)
            return None
        except Exception:
            # The 200 headers are already sent: end the stream with an error event rather than cut it off.
            logger.exception("starting a thread failed")
            return None
        thread_id = ThreadId(thread.thread_id)
        return _sse("thread", {"thread_id": thread.thread_id})

    return _stream(answer, start, _recorder(conversations, principal.user_id, lambda: thread_id))


@router.post(
    "/threads/{thread_id}/questions",
    operation_id="ask_in_thread",
    response_class=StreamingResponse,
    responses=ASK_IN_THREAD_RESPONSE,
)
async def ask_in_thread(
    thread_id: uuid.UUID,
    body: AskRequest,
    principal: CurrentPrincipal,
    token: BearerToken,
    conversations: Conversations,
    agent: Agent,
) -> StreamingResponse:
    """Ask in the learner's conversation (US-4c): a limited conversation searches only its listed documents, whose
    ids are read here, never from the question."""
    tid = ThreadId(str(thread_id))
    try:
        # Ownership first, so another learner's thread is a 404 whatever their library holds.
        listed = await run_in_threadpool(conversations.search_documents, tid, principal.user_id)
        await run_in_threadpool(conversations.require_documents, principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except (NoDocumentsError, ThreadArchivedError) as e:
        raise HTTPException(409, str(e)) from None
    answer = await _open(agent, token, body.question, listed)

    async def start() -> bytes | None:
        return _sse("thread", {"thread_id": tid})

    return _stream(answer, start, _recorder(conversations, principal.user_id, lambda: tid))


class UpdateThreadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Checked by the thread (trimmed, 1-120 characters), so a refusal carries the learner's message.
    title: str | None = None
    search_scope: Literal["library", "listed"] | None = None

    @model_validator(mode="after")
    def _one_change(self) -> Self:
        if self.title is None and self.search_scope is None:
            raise ValueError("Change the title or the search scope")
        return self


class ThreadResponse(BaseModel):
    thread_id: str
    title: str | None
    search_scope: Literal["library", "listed"]


def _thread_response(thread: Thread) -> ThreadResponse:
    return ThreadResponse(thread_id=thread.thread_id, title=thread.title, search_scope=thread.search_scope.value)


@router.get(
    "/threads/{thread_id}",
    operation_id="get_thread",
    responses={404: {"description": "Not the caller's conversation."}},
)
def get_thread(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> ThreadResponse:
    """The learner's conversation: its title and search scope (PRD US-4c)."""
    try:
        return _thread_response(conversations.get_thread(ThreadId(str(thread_id)), principal.user_id))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.patch(
    "/threads/{thread_id}",
    operation_id="update_thread",
    responses={
        404: {"description": "Not the caller's conversation."},
        409: {"description": "The conversation is archived, or has no documents to limit the search to."},
        422: {"description": "Nothing to change, or the title is empty or longer than 120 characters."},
    },
)
def update_thread(
    thread_id: uuid.UUID, body: UpdateThreadRequest, principal: CurrentPrincipal, conversations: Conversations
) -> ThreadResponse:
    """Rename the learner's conversation (PRD US-13) and/or limit its search to its documents (US-4c)."""
    scope = SearchScope(body.search_scope) if body.search_scope is not None else None
    try:
        thread = conversations.update_thread(
            ThreadId(str(thread_id)), principal.user_id, title=body.title, search_scope=scope
        )
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except (ThreadArchivedError, NoListedDocumentsError) as e:
        raise HTTPException(409, str(e)) from None
    except InvalidTitleError as e:
        raise HTTPException(422, str(e)) from None
    return _thread_response(thread)


class ThreadDocumentResponse(BaseModel):
    document_id: str
    title: str
    authors: list[str]
    year: int | None
    archived: bool
    deleted: bool
    added_by: Literal["answer", "learner"]
    used: bool


class AddThreadDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=50)]


def _response(d: DocumentUsed) -> ThreadDocumentResponse:
    return ThreadDocumentResponse(
        document_id=d.document_id,
        title=d.title,
        authors=list(d.authors),
        year=d.year,
        archived=d.archived,
        deleted=d.deleted,
        added_by=d.added_by,
        used=d.used,
    )


@router.get(
    "/threads/{thread_id}/documents",
    operation_id="list_thread_documents",
    responses={404: {"description": "Not the caller's conversation."}},
)
def list_thread_documents(
    thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> list[ThreadDocumentResponse]:
    """The conversation's documents: those its answers drew on and those the learner added (PRD US-4b, US-4c)."""
    try:
        used = conversations.documents_used(ThreadId(str(thread_id)), principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    return [_response(d) for d in used]


@router.post(
    "/threads/{thread_id}/documents",
    operation_id="add_thread_documents",
    responses={404: {"description": "Not the caller's conversation, or a document that isn't their ready one."}},
)
def add_thread_documents(
    thread_id: uuid.UUID, body: AddThreadDocumentsRequest, principal: CurrentPrincipal, conversations: Conversations
) -> list[ThreadDocumentResponse]:
    """Add the learner's ready, non-archived documents to the conversation's list (PRD US-4c); returns the list."""
    try:
        listed = conversations.add_documents(
            ThreadId(str(thread_id)), principal.user_id, [DocumentId(str(d)) for d in body.document_ids]
        )
    except (ThreadNotFoundError, DocumentNotAvailableError) as e:
        raise HTTPException(404, str(e)) from None
    return [_response(d) for d in listed]


@router.delete(
    "/threads/{thread_id}/documents/{document_id}",
    operation_id="remove_thread_document",
    status_code=204,
    responses={404: {"description": "Not the caller's conversation."}},
)
def remove_thread_document(
    thread_id: uuid.UUID, document_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> None:
    """Take a document off the conversation's list (PRD US-4c); the document and old citations are unchanged."""
    try:
        conversations.remove_document(ThreadId(str(thread_id)), principal.user_id, DocumentId(str(document_id)))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
