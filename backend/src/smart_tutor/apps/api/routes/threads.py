"""Thread routes (tutoring module): ask the first question of a new thread, optionally started from one of the
learner's documents, or a later one in an existing thread; an answer draws on all of the learner's ready documents, or
only the thread's listed ones once the learner limits its search scope (US-4c); a question in an existing thread is
sent with its last turns (ADR 0015). Answered as SSE (PRD §9.2); the
answer is kept as a turn when it is done, with the documents it drew on, and the turns and documents are listed per
thread; the learner adds documents to that list and removes them (US-4c). The learner can rename a thread and set or
read its search scope. A learner with no ready, non-archived document still gets a stream: the agent's request
to upload a document (a "no_documents" decline), kept as a turn like any decline (US-3, US-10). Each ask gets a run
id that names its trace and is kept with the turn. The learner lists their active conversations, newest activity
first (US-13); the learner archives and restores a conversation, and an archived one is read-only (US-13). The
learner rates a kept answer or decline 👍/👎 (PRD §10.2); the rating is saved with the turn,
then sent to Langfuse as a `learner_rating` score on the ask's trace. A guard trip's `replace` event keeps
the turn as the guard message, with no documents used."""

import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Literal, Self

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from smart_tutor.apps.api.agent_client import AgentAnswer, AgentUnavailableError
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal, Subjects
from smart_tutor.apps.api.routes.knowledge import SubjectResponse
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import DocumentId, RunId, SubjectId, ThreadId, UserId
from smart_tutor.tutoring.application import (
    AnsweredTurn,
    Decline,
    DocumentNotAvailableError,
    DocumentUsed,
    HistoryTurn,
    InvalidTitleError,
    NoListedDocumentsError,
    Rating,
    SearchScope,
    Thread,
    ThreadArchivedError,
    ThreadNotFoundError,
    TurnCitation,
    TurnNotFoundError,
    TurnView,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["tutoring"])

UNAVAILABLE = "The tutor is unavailable. Try again in a moment."
# Proxies must pass each event on as it comes, and nothing may cache the answer.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
SSE_RESPONSE: dict[int | str, dict[str, object]] = {
    200: {
        "description": (
            "Server-sent events: thread, then delta*, citations, done; or decline then done "
            "(no_documents: nothing readable, upload first; limited: the listed documents don't cover it; "
            "off_topic: not a study question, declined before search); "
            "or delta*, replace, done when a guard trips (the learner sees replace's text instead of the partial "
            "answer); or error."
        ),
        "content": {"text/event-stream": {"schema": {"type": "string"}}},
    },
    404: {"description": "A document that isn't the caller's ready one."},
}
ASK_IN_THREAD_RESPONSE: dict[int | str, dict[str, object]] = {
    **SSE_RESPONSE,
    404: {"description": "Not the caller's conversation."},
    409: {"description": "The conversation is archived."},
}


class QuestionRequest(BaseModel):
    # No user id: the thread's owner comes from the token (PRD §9.3). Unknown fields are refused.
    model_config = ConfigDict(extra="forbid")
    # Stripped before the length check, so a blank question is a 422; the agent gets the stripped text.
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class AskRequest(QuestionRequest):
    # Started from a document (US-4c): listed in the new thread; answers still search all documents.
    document_id: uuid.UUID | None = None


def _sse(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


_EVENT_END = b"\n\n"
_UNAVAILABLE_EVENT = _sse("error", {"code": "unavailable", "message": UNAVAILABLE})

# Starts the thread; its `thread` event, or None when it couldn't start.
StartThread = Callable[[], Awaitable[bytes | None]]


@dataclass
class _Seen:
    """What the learner saw of one answer; kept as a turn when it ends with `done`."""

    answer: str = ""
    citations: tuple[TurnCitation, ...] = ()
    decline: Decline | None = None
    document_ids: tuple[DocumentId, ...] = ()
    tripped: bool = False  # a guard's `replace` came: no documents used, no citations kept


# Keeps the answer as a turn of the thread that started, with its documents used; never raises.
RecordAnswer = Callable[[_Seen], Awaitable[None]]


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


def _document_ids(data: object) -> tuple[DocumentId, ...]:
    """The document ids of a `sources` event's data, canonical; () when it isn't one.

    An id that isn't a UUID is dropped rather than failing the insert, which would lose the whole turn.
    """
    ids = data.get("document_ids") if isinstance(data, dict) else None
    if not isinstance(ids, list):
        logger.warning("the agent's sources event was malformed")
        return ()
    kept = tuple(DocumentId(str(uuid.UUID(i))) for i in ids if _is_uuid(i))
    if len(kept) != len(ids):
        logger.warning("the agent's sources were partly malformed")
    return kept


def _is_uuid(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


def _citation(item: object) -> TurnCitation | None:
    if not isinstance(item, dict):
        return None
    n, chunk_id, document_id, page = item.get("n"), item.get("chunk_id"), item.get("document_id"), item.get("page")
    if not isinstance(n, int) or isinstance(n, bool) or not isinstance(chunk_id, str) or not _is_uuid(document_id):
        return None
    if page is not None and (not isinstance(page, int) or isinstance(page, bool)):
        return None
    # Canonical, so a braced or upper-case id still matches the document at read time.
    return TurnCitation(n, DocumentId(str(uuid.UUID(str(document_id)))), chunk_id, page)


def _citations(data: object) -> tuple[TurnCitation, ...]:
    """The well-formed citations of a `citations` event; the learner already has the event as sent."""
    items = data.get("citations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        logger.warning("the agent's citations event was malformed")
        return ()
    kept = tuple(c for c in map(_citation, items) if c is not None)
    if len(kept) != len(items):
        logger.warning("the agent's citations were partly malformed")
    return kept


def _decline(data: object) -> Decline | None:
    code = data.get("code") if isinstance(data, dict) else None
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(code, str) or not isinstance(message, str):
        logger.warning("the agent's decline event was malformed")
        return None
    return Decline(code, message)


def _replace(data: object) -> Decline | None:
    """A guard trip's `replace` event (US-6, D29): the learner sees `text` in place of the partial answer."""
    code = data.get("code") if isinstance(data, dict) else None
    text = data.get("text") if isinstance(data, dict) else None
    if not isinstance(code, str) or not isinstance(text, str):
        logger.warning("the agent's replace event was malformed")
        return None
    return Decline(code, text)


def _delta(data: object) -> str:
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) else ""


async def _relay(answer: AgentAnswer, start: StartThread, record: RecordAnswer) -> AsyncIterator[bytes]:
    """The agent's events after a `thread` event, each forwarded only once complete.

    The thread starts on the agent's first event unless it is an `error`, which is relayed as-is and starts none. If
    the stream drops inside an event, the partial event is dropped so the error event that follows stays a
    well-formed event of its own.

    The agent's `sources` event is kept back; on `done`, if the thread started, the turn and its documents are kept
    before `done` is forwarded. A `replace` (a guard trip) empties what was kept: the turn is the guard message, with
    no answer, citations, or documents used; a `sources` or `citations` event after it is ignored.

    A stream that ends without `done` or `error` ends with an unavailable error event.
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
        seen = _Seen()
        ended = False
        event: bytes | None = first
        while event is not None:
            parsed = _event(event)
            name = parsed[0] if parsed else None
            if parsed and name == "sources":
                if not seen.tripped:
                    seen.document_ids = _document_ids(parsed[1])
            else:
                if parsed and name == "delta":
                    seen.answer += _delta(parsed[1])
                elif parsed and name == "replace":
                    seen = _Seen(decline=_replace(parsed[1]), tripped=True)
                elif parsed and name == "citations":
                    if not seen.tripped:
                        seen.citations = _citations(parsed[1])
                elif parsed and name == "decline":
                    seen.decline = _decline(parsed[1])
                if name == "done" and started:
                    await record(seen)
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


async def _open(
    agent: Agent,
    token: str,
    question: str,
    document_ids: Sequence[str] | None,
    thread_id: ThreadId,
    run_id: RunId,
    history: Sequence[HistoryTurn] = (),
) -> AgentAnswer:
    try:
        return await agent.open_answer(
            token, question, document_ids, thread_id=thread_id, run_id=run_id, history=history
        )
    except UnauthenticatedError:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None


def _recorder(
    conversations: Conversations,
    user_id: UserId,
    question: str,
    thread_id: Callable[[], ThreadId | None],
    run_id: RunId,
) -> RecordAnswer:
    """Keeps an answer as a turn of the thread `thread_id()` gives (None: none started, so nothing to keep)."""

    async def record(seen: _Seen) -> None:
        tid = thread_id()
        if tid is None:
            return
        turn = AnsweredTurn(question, seen.answer, seen.citations, seen.decline, seen.document_ids, run_id)
        try:
            await run_in_threadpool(conversations.record_turn, tid, user_id, turn)
        except Exception as e:
            # The learner already has the answer: log it and still end the stream with `done`. Only the class name:
            # a database error's message carries the bound question, answer, and user id.
            logger.error("keeping the turn failed (%s)", type(e).__name__)

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
    document_id = DocumentId(str(body.document_id)) if body.document_id else None
    if document_id is not None:
        try:
            await run_in_threadpool(conversations.require_readable, principal.user_id, document_id)
        except DocumentNotAvailableError as e:
            raise HTTPException(404, str(e)) from None
    new_id = ThreadId(str(uuid.uuid4()))
    run_id = RunId(str(uuid.uuid4()))
    answer = await _open(agent, token, body.question, None, new_id, run_id)

    thread_id: ThreadId | None = None

    async def start() -> bytes | None:
        nonlocal thread_id
        try:
            thread = await run_in_threadpool(
                conversations.start_thread, principal.user_id, body.question, document_id, thread_id=new_id
            )
        except DocumentNotAvailableError as e:
            logger.warning("the thread was refused: %s", e)
            return None
        except Exception:
            # The 200 headers are already sent: end the stream with an error event rather than cut it off.
            logger.exception("starting a thread failed")
            return None
        thread_id = ThreadId(thread.thread_id)
        return _sse("thread", {"thread_id": thread.thread_id, "run_id": run_id})

    recorder = _recorder(conversations, principal.user_id, body.question, lambda: thread_id, run_id)
    return _stream(answer, start, recorder)


@router.post(
    "/threads/{thread_id}/questions",
    operation_id="ask_in_thread",
    response_class=StreamingResponse,
    responses=ASK_IN_THREAD_RESPONSE,
)
async def ask_in_thread(
    thread_id: uuid.UUID,
    body: QuestionRequest,
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
        # The question moves the conversation to the top of the list, once it is accepted and before the agent runs.
        await run_in_threadpool(conversations.note_question, tid, principal.user_id)
        # The agent also gets the conversation's last turns (PRD §9.2 step 3), read through owner-scoped SQL after
        # the ownership check (ADR 0015).
        history = await run_in_threadpool(conversations.history, tid, principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except ThreadArchivedError as e:
        raise HTTPException(409, str(e)) from None
    run_id = RunId(str(uuid.uuid4()))
    answer = await _open(agent, token, body.question, listed, tid, run_id, history)

    async def start() -> bytes | None:
        return _sse("thread", {"thread_id": tid, "run_id": run_id})

    return _stream(answer, start, _recorder(conversations, principal.user_id, body.question, lambda: tid, run_id))


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
    status: Literal["active", "archived"]


def _thread_response(thread: Thread) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        search_scope=thread.search_scope.value,
        status=thread.status.value,
    )


class ThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str | None
    subjects: list[SubjectResponse]  # of its documents used that still exist, by the learner's names (D11)
    documents: int
    last_activity: datetime


@router.get("/threads", operation_id="list_threads")
def list_threads(
    principal: CurrentPrincipal,
    conversations: Conversations,
    subjects: Subjects,
    archived: bool = False,
    subject_id: Annotated[list[uuid.UUID], Query(max_length=100)] = [],  # noqa: B006 - FastAPI copies the default
    active_from: date | None = None,
    active_to: date | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,  # a title is at most 120 characters (US-13)
) -> list[ThreadSummaryResponse]:
    """The learner's active conversations, or with `archived=true` the archived ones, newest last activity first
    (PRD US-13): title, subjects of the documents used (deleted ones excluded), number of documents, last activity.

    `subject_id` repeats; a conversation matches when any of its listed documents that still exist has any of them.
    `active_from` and `active_to` are inclusive calendar days of last activity in the app time zone (D27). `q` is a
    case-insensitive part of the title; answers are not searched (Q63). The filters combine; blank `q` is ignored.
    """
    summaries = conversations.list_threads(
        principal.user_id,
        archived=archived,
        subject_ids=[SubjectId(str(s)) for s in subject_id],
        active_from=active_from,
        active_to=active_to,
        title=q,
    )
    names = subjects.names_for(principal.user_id, {s for t in summaries for s in t.subject_ids})
    return [
        ThreadSummaryResponse(
            thread_id=t.thread_id,
            title=t.title,
            subjects=[SubjectResponse(subject_id=s, name=names[s]) for s in t.subject_ids if s in names],
            documents=t.documents,
            last_activity=t.last_activity,
        )
        for t in summaries
    ]


@router.post(
    "/threads/{thread_id}/archive",
    operation_id="archive_thread",
    responses={404: {"description": "Not the caller's conversation."}},
)
def archive_thread(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> ThreadResponse:
    """Archive the learner's conversation (PRD US-13): it leaves the active list and becomes read-only; its history,
    documents used, and title stay. Archiving an archived one changes nothing."""
    try:
        return _thread_response(conversations.archive_thread(ThreadId(str(thread_id)), principal.user_id))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.post(
    "/threads/{thread_id}/restore",
    operation_id="restore_thread",
    responses={404: {"description": "Not the caller's conversation."}},
)
def restore_thread(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> ThreadResponse:
    """Restore the learner's archived conversation: active again; restoring an active one changes nothing."""
    try:
        return _thread_response(conversations.restore_thread(ThreadId(str(thread_id)), principal.user_id))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None


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
    responses={
        404: {"description": "Not the caller's conversation, or a document that isn't their ready one."},
        409: {"description": "The conversation is archived."},
    },
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
    except ThreadArchivedError as e:
        raise HTTPException(409, str(e)) from None
    return [_response(d) for d in listed]


@router.delete(
    "/threads/{thread_id}/documents/{document_id}",
    operation_id="remove_thread_document",
    status_code=204,
    responses={
        404: {"description": "Not the caller's conversation."},
        409: {"description": "The conversation is archived."},
    },
)
def remove_thread_document(
    thread_id: uuid.UUID, document_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> None:
    """Take a document off the conversation's list (PRD US-4c); the document and old citations are unchanged."""
    try:
        conversations.remove_document(ThreadId(str(thread_id)), principal.user_id, DocumentId(str(document_id)))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except ThreadArchivedError as e:
        raise HTTPException(409, str(e)) from None


class TurnCitationResponse(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None
    archived: bool
    deleted: bool


class TurnDeclineResponse(BaseModel):
    code: str
    message: str


class TurnResponse(BaseModel):
    question: str
    answer: str
    citations: list[TurnCitationResponse]
    decline: TurnDeclineResponse | None
    created_at: datetime
    run_id: str | None = Field(
        description=(
            "The ask's trace id (its run id), for attaching a rating (#227); "
            "null for turns kept before it was recorded."
        )
    )
    rating: Literal["up", "down"] | None = Field(description="The learner's rating (PRD §10.2); null until rated.")


def _turn_response(t: TurnView) -> TurnResponse:
    return TurnResponse(
        question=t.question,
        answer=t.answer,
        citations=[
            TurnCitationResponse(
                n=c.n,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.title,
                page=c.page,
                archived=c.archived,
                deleted=c.deleted,
            )
            for c in t.citations
        ],
        decline=TurnDeclineResponse(code=t.decline.code, message=t.decline.message) if t.decline else None,
        created_at=t.created_at,
        run_id=t.run_id,
        rating=t.rating.value if t.rating else None,
    )


@router.get(
    "/threads/{thread_id}/turns",
    operation_id="list_thread_turns",
    responses={404: {"description": "Not the caller's conversation."}},
)
def list_thread_turns(
    thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> list[TurnResponse]:
    """The conversation's turns, oldest first: each question with its answer and citations, or its decline (PRD
    US-13). Citations resolve now: display title, archived, or "Deleted document"."""
    try:
        turns = conversations.turns(ThreadId(str(thread_id)), principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    return [_turn_response(t) for t in turns]


class RateTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["up", "down"]


class TurnRatingResponse(BaseModel):
    rating: Literal["up", "down"]


@router.put(
    "/threads/{thread_id}/turns/{run_id}/rating",
    operation_id="rate_turn",
    responses={404: {"description": "Not the caller's conversation, or no such answer in it."}},
)
def rate_turn(
    thread_id: uuid.UUID,
    run_id: uuid.UUID,
    body: RateTurnRequest,
    principal: CurrentPrincipal,
    conversations: Conversations,
) -> TurnRatingResponse:
    """Rate an answer or decline of the learner's conversation helpful ("up") or not ("down"); a new rating replaces
    the last (PRD §10.2). Saved with the turn, then sent to Langfuse as a `learner_rating` score on the ask's
    trace."""
    try:
        conversations.rate_turn(ThreadId(str(thread_id)), principal.user_id, RunId(str(run_id)), Rating(body.rating))
    except (ThreadNotFoundError, TurnNotFoundError) as e:
        raise HTTPException(404, str(e)) from None
    return TurnRatingResponse(rating=body.rating)
