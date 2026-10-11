# No Active Documents Left Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner whose documents are all archived or deleted keeps reading their conversations, and a new question streams the US-3 request to upload a document ("Upload", no error) without the agent calling the model (#111).

**Architecture:** The agent decides, not the API: its search step notices an empty readable set (MCP search returns nothing library-wide), and the answer step turns it into a `decline` event with code `no_documents` before any model call. The API stops refusing with 409 when the learner has no ready documents, relays the stream, and keeps the turn like any decline, so the conversation's history shows it. The web asks in the open conversation when the learner has no active documents (so the request sits under the history) and renders the decline with an Upload link.

**Tech Stack:** Python 3 / FastAPI / LangGraph (agent, API), pytest with the fakes in `backend/tests/fakes/`; React + TypeScript + Vite, Vitest + Testing Library (web).

**Spec:** GitHub issue #111; PRD `sdd/prd.md` §8 US-3, US-10, §9.2 step 1, §9.3 steps 4–5. Mockup round v0.10 (tag `design-v0.10`), states `chat-no-active-documents` and `chat-answer-citations`.

## Global Constraints

- Upload request copy (from the v0.10 prototype, `chat.js` `nodocs` message), exactly:
  - message (sent by the agent, stored with the turn): `None of your documents can be used right now: they are all archived or deleted.`
  - muted line (web only): `Upload a document to get an answer. Your earlier answers stay readable.`
  - action (web only): a secondary `LinkButton` labelled `Upload` with the `Upload` icon, to `/library`.
- Decline codes on the wire: `"limited"` (existing) and `"no_documents"` (new). SSE event: `event: decline` / `data: {"code": "no_documents", "message": "<message>"}`, then `done`.
- The model is never called for a `no_documents` turn.
- `can_read` stays the only access rule; nothing new reads documents outside it. `GET /chunks/{id}` already resolves archived documents and 404s others' (`backend/tests/isolation/test_chunks.py`); keep it that way.
- Checks before each commit, from `backend/`: `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. From `web/` when web changed: `npm run build` and `npx vitest run`.
- Commit subjects in the imperative mood; the body says why; end every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A limited conversation (`document_ids` given) whose listed documents are all archived, while other documents are active: must stay the `limited` decline (with "Search all my documents"), not the upload request — Task 1 test `test_a_limited_search_with_unreadable_listed_documents_but_an_active_library_is_limited`.
- A limited conversation with nothing active at all: must be the upload request, not the limited decline — Task 1 test `test_a_limited_search_with_nothing_readable_anywhere_asks_for_an_upload`.
- Another learner's ready documents must never make an archived-only learner's readable set non-empty — Task 2 isolation test `test_an_archived_only_learner_gets_an_empty_readable_set_while_another_has_documents`.
- A reopened conversation with no active documents: the question must not start a new thread or move the URL, and the history must stay above the request — Task 3 test `with no active documents a question goes to this conversation, under its history`.
- A no_documents turn reloaded from history (after the learner later uploads) shows its message; its Upload link appears only on the last turn — Task 3 test `a no_documents decline in the history shows its message, with Upload only on the last turn`.

---

### Task 1: The agent turns an empty readable set into the upload request

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/application/answer.py:11` (replace `NO_CHUNKS_ANSWER`)
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (export `NO_DOCUMENTS_DECLINE` instead of `NO_CHUNKS_ANSWER`)
- Modify: `backend/src/smart_tutor/apps/agent/state.py`
- Modify: `backend/src/smart_tutor/apps/agent/nodes/search.py`
- Modify: `backend/src/smart_tutor/apps/agent/nodes/answer.py`
- Modify: `backend/src/smart_tutor/apps/agent/server.py` (docstring and `answer_events`)
- Test: `backend/tests/unit/apps/agent/test_graph.py`, `backend/tests/unit/apps/agent/test_server.py`, `backend/tests/unit/tutoring/test_answer.py`

**Interfaces:**
- Produces: `smart_tutor.tutoring.application.NO_DOCUMENTS_DECLINE: str` (the message above). `AskState` loses `declined: bool` and gains `no_documents: bool` and `decline: DeclineCode` where `DeclineCode = Literal["limited", "no_documents"]` (defined in `apps/agent/state.py`). The agent's SSE `decline` event carries `code` `"limited"` or `"no_documents"`.
- Removes: `NO_CHUNKS_ANSWER` (the fixed "I couldn't find anything" answer). It is unreachable now: a library-wide search returns no chunk only when the learner has no ready, non-archived document, which is the upload request.

- [ ] **Step 1: Write the failing graph tests**

In `backend/tests/unit/apps/agent/test_graph.py`, change the import `from smart_tutor.tutoring.application import NO_CHUNKS_ANSWER, Retriever` to `from smart_tutor.tutoring.application import Retriever`, add `from collections.abc import Sequence` at the top, and replace `test_no_chunks_gives_the_fixed_answer_without_calling_the_model` with:

```python
class ListedUnreadable(FakeRetriever):
    """Finds its chunks library-wide only: the listed documents can't be read (archived, deleted, or another's)."""

    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        found = await super().search(query, k, document_ids)
        return [] if document_ids is not None else found


async def test_an_empty_readable_set_asks_for_an_upload_without_calling_the_model() -> None:
    retriever = FakeRetriever([])
    graph = build_graph(lambda token: retriever, fake_chat_model())  # no scripted reply: a call would fail
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t"))
    assert out["decline"] == "no_documents" and out["answer"] == "" and out["citations"] == []
    assert retriever.calls == [("What is attention?", 5, None)]  # library-wide: no second search


async def test_a_limited_search_with_nothing_readable_anywhere_asks_for_an_upload() -> None:
    retriever = FakeRetriever([])
    graph = build_graph(lambda token: retriever, fake_chat_model())
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert out["decline"] == "no_documents"
    assert retriever.calls == [("What is attention?", 5, ["d1"]), ("What is attention?", 1, None)]


async def test_a_limited_search_with_unreadable_listed_documents_but_an_active_library_is_limited() -> None:
    retriever = ListedUnreadable(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model())
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert out["decline"] == "limited"
    assert retriever.calls == [("What is attention?", 5, ["d1"]), ("What is attention?", 1, None)]


async def test_a_limited_search_that_finds_chunks_searches_once() -> None:
    retriever = FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")))
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["answer"] == "It weighs tokens [1]."
    assert retriever.calls == [("What is attention?", 5, ["d1"])]
```

Also add to `test_searches_all_documents_with_the_context_token_then_answers_with_citations` the line `assert "decline" not in out`.

- [ ] **Step 2: Write the failing server tests**

In `backend/tests/unit/apps/agent/test_server.py` add `from collections.abc import Sequence` and a module constant:

```python
NO_DOCUMENTS = "None of your documents can be used right now: they are all archived or deleted."
```

Replace `test_no_chunks_streams_the_fixed_answer` with:

```python
def test_an_empty_readable_set_streams_the_upload_request_without_calling_the_model() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(lambda token: FakeRetriever([]), fake_chat_model(), 0.3)  # no replies: any model call fails
    c = TestClient(create_app(Settings(), verifier=verifier, graph=graph))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got == [("decline", {"code": "no_documents", "message": NO_DOCUMENTS}), ("done", {})]
```

Replace `test_a_limited_search_with_no_chunks_declines` with two tests:

```python
def test_a_limited_search_with_nothing_readable_anywhere_streams_the_upload_request() -> None:
    c, _ = client(FakeRetriever([]))
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    assert events(body) == [("decline", {"code": "no_documents", "message": NO_DOCUMENTS}), ("done", {})]


class _ListedUnreadable(FakeRetriever):
    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        found = await super().search(query, k, document_ids)
        return [] if document_ids is not None else found


def test_a_limited_search_whose_listed_documents_cant_be_read_declines_as_limited() -> None:
    c, _ = client(_ListedUnreadable([CHUNK]))
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    assert events(body) == [
        ("decline", {"code": "limited", "message": "These documents don't cover this."}),
        ("done", {}),
    ]
```

- [ ] **Step 3: Update the answer-module test**

In `backend/tests/unit/tutoring/test_answer.py` change the import to `from smart_tutor.tutoring.application import NO_DOCUMENTS_DECLINE, answer_messages, cited_chunks, covers` and replace `test_no_chunks_answer_is_plain` with:

```python
def test_the_no_documents_decline_says_nothing_can_be_used() -> None:
    assert NO_DOCUMENTS_DECLINE == "None of your documents can be used right now: they are all archived or deleted."
```

- [ ] **Step 4: Run the tests to see them fail**

Run (from `backend/`): `uv run pytest tests/unit/apps/agent tests/unit/tutoring/test_answer.py -q`
Expected: FAIL — `ImportError: cannot import name 'NO_DOCUMENTS_DECLINE'` (collection error) for `test_answer.py`, and `KeyError: 'decline'` / event mismatches in the agent tests.

- [ ] **Step 5: Implement**

`backend/src/smart_tutor/tutoring/application/answer.py`: replace the `NO_CHUNKS_ANSWER` line with

```python
# The US-3 request to upload a document: the learner has no ready, non-archived document (PRD §9.2 step 1).
NO_DOCUMENTS_DECLINE = "None of your documents can be used right now: they are all archived or deleted."
```

`backend/src/smart_tutor/tutoring/application/__init__.py`: replace `NO_CHUNKS_ANSWER` with `NO_DOCUMENTS_DECLINE` in both the import and `__all__` (keep `__all__` sorted as it is).

`backend/src/smart_tutor/apps/agent/state.py`: add `from typing import Literal, TypedDict` and replace `declined: bool` so the end of the file reads:

```python
# "limited": a limited search that doesn't cover the question (US-4c); "no_documents": nothing is readable (US-3).
DeclineCode = Literal["limited", "no_documents"]


class AskState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    chunks: list[RetrievedChunk]
    no_documents: bool  # the readable set is empty: the learner has no ready, non-archived document
    answer: str
    citations: list[Citation]
    decline: DeclineCode
```

`backend/src/smart_tutor/apps/agent/nodes/search.py`: update the module docstring's first line to `"""Search step (PRD §9.2 step 1): all the learner's ready documents, or only the conversation's listed ones` (keep the rest), and replace the body of `search`:

```python
    async def search(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        retriever = retriever_for(runtime.context.access_token)
        question, document_ids = state["question"], state.get("document_ids")
        chunks = await retriever.search(question, K, document_ids)
        # An empty readable set gets the upload request. A limited search that found nothing only says its listed
        # documents can't be read, so one library-wide chunk tells whether anything else can.
        no_documents = not chunks and (document_ids is None or not await retriever.search(question, 1, None))
        return {"chunks": chunks, "no_documents": no_documents}
```

`backend/src/smart_tutor/apps/agent/nodes/answer.py`: module docstring becomes

```python
"""Answer step (PRD §9.2): stream the model's answer over quoted chunks.

Nothing readable ends in the upload request (US-3), and a search limited to given documents that doesn't cover the
question in a decline (US-4c); the model is called for neither.
"""
```

change the import to `from smart_tutor.tutoring.application import answer_messages, cited_chunks, covers`, and the body of `answer` to:

```python
    async def answer(state: AskState) -> AskState:
        if state.get("no_documents"):
            return {"answer": "", "citations": [], "decline": "no_documents"}
        chunks = state.get("chunks", [])
        if state.get("document_ids") is not None and not covers(chunks, answer_floor):
            return {"answer": "", "citations": [], "decline": "limited"}
        reply = await model.ainvoke(answer_messages(state["question"], chunks))
        text = reply.text
        return {"answer": text, "citations": [c.citation(n) for n, c in cited_chunks(text, chunks)]}
```

(After the two checks `chunks` is never empty: library-wide, empty means no documents; limited, empty fails `covers`.)

`backend/src/smart_tutor/apps/agent/server.py`:
- Import `from smart_tutor.tutoring.application import LIMITED_DECLINE, NO_DOCUMENTS_DECLINE, RetrievedChunk`.
- Below `STREAM_MODES` add:

```python
DECLINE_MESSAGES = {"limited": LIMITED_DECLINE, "no_documents": NO_DOCUMENTS_DECLINE}
```

- Replace the module docstring with:

```python
"""Agent HTTP server (internal ClusterIP): POST /ask streams one answer as SSE (PRD §9.2, ADR 0007).

Events, each ``event: <name>\\ndata: <json>\\n\\n``: ``delta`` {"text"} in order, then ``sources``
{"document_ids"} once (the distinct documents of the chunks given to the model, in rank order; meant for the API,
which records them and never forwards the event), then ``citations`` once ({"citations": [{"n", "chunk_id",
"document_id", "document_title", "page"}]}, ``n`` being the answer's ``[n]`` marker), then ``done``; or ``error``
{"code": "unauthenticated" | "unavailable", "message"}, which ends the stream and may come first.

A turn the model doesn't answer is ``decline`` {"code", "message"} then ``done``, with no ``delta``, ``sources``, or
``citations``: ``no_documents`` when the learner has nothing readable (no ready, non-archived document; US-3), or,
for a request with ``document_ids`` (only those documents are searched), ``limited`` when none of the chunks found
scores at least ``answer_floor`` (US-4c).
"""
```

- In `answer_events`, delete `streamed = False` and `streamed = True`, and replace the `"answer"` update branch with:

```python
            elif part["type"] == "updates" and "answer" in part["data"]:
                update = part["data"]["answer"]
                if (code := update.get("decline")) is not None:
                    yield sse("decline", {"code": code, "message": DECLINE_MESSAGES[code]})
                    continue
                yield sse("sources", {"document_ids": list(dict.fromkeys(c.document_id for c in chunks))})
                citations = [
```

(keep the rest of the branch as it is; the `if meta.get("langgraph_node") == "answer" and chunk.text:` line now just yields the delta.)

- [ ] **Step 6: Run the tests to see them pass**

Run (from `backend/`): `uv run pytest tests/unit/apps/agent tests/unit/tutoring -q`
Expected: PASS. Then `grep -rn "NO_CHUNKS_ANSWER\|declined\|couldn't find anything" src tests evals` — expected: no matches.

- [ ] **Step 7: Full backend checks and commit**

Run the backend checks from Global Constraints. Then:

```bash
git add backend/src/smart_tutor/tutoring/application backend/src/smart_tutor/apps/agent backend/tests/unit/apps/agent backend/tests/unit/tutoring/test_answer.py
git commit -m "Ask for an upload when nothing is readable, without calling the model" -m "PRD §9.2 step 1: an empty readable set gets the US-3 request to upload a document (#111). The search step tells it apart from a limited search whose listed documents can't be read with one library-wide chunk, so a limited conversation over an active library still gets its limited decline. The fixed no-chunks answer was only reachable in this case and is removed.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The API streams the upload request instead of refusing with 409

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py` (module docstring, `SSE_RESPONSE`, `ASK_IN_THREAD_RESPONSE`, imports, `ask_in_new_thread`, `ask_in_thread`)
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py` (remove `require_documents`, its call in `start_thread`, the `NoDocumentsError` import)
- Modify: `backend/src/smart_tutor/tutoring/domain/errors.py` (remove `NoDocumentsError`)
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (remove the `NoDocumentsError` export)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py:114` (remove `has_ready_documents`, now unused)
- Modify: `web/src/api/openapi.json` and `web/src/api/generated/*` (regenerated, not hand-edited)
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/isolation/test_threads.py`, `backend/tests/isolation/test_search.py`

**Interfaces:**
- Consumes: the agent's `decline` event with code `no_documents` (Task 1); the API relay already keeps any `decline` as the turn's `Decline(code, message)`.
- Produces: `POST /threads` and `POST /threads/{id}/questions` answer 200 with the SSE stream for a learner with no ready documents (no 409 for that any more). `POST /threads/{id}/questions` still answers 409 for an archived conversation; `POST /threads` keeps its 404 for a starting document that isn't the learner's ready, non-archived one.
- Removes: `ConversationService.require_documents`, `tutoring` `NoDocumentsError`, `DocumentService.has_ready_documents`.

- [ ] **Step 1: Write the failing route tests**

In `backend/tests/unit/apps/api/test_thread_routes.py` add the module constant (next to `AGENT_ANSWER`):

```python
NO_DOCUMENTS = (
    b'event: decline\ndata: {"code": "no_documents", "message": "None of your documents can be used right now: '
    b'they are all archived or deleted."}\n\n'
    b"event: done\ndata: {}\n\n"
)


def sse_no_documents(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=NO_DOCUMENTS, headers={"content-type": "text/event-stream"})
```

Replace `test_no_ready_documents_is_409_before_any_thread_or_agent_call` with:

```python
def test_without_ready_documents_the_agents_upload_request_is_streamed_and_kept() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen, sse_no_documents), ready_document=False)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and len(seen) == 1
    [thread] = threads.threads.values()
    assert response.text == f'event: thread\ndata: {{"thread_id": "{thread.thread_id}"}}\n\n' + NO_DOCUMENTS.decode()
    [turn] = threads.turns(ThreadId(thread.thread_id), UserId("ada"))
    assert turn.answer == "" and turn.decline is not None and turn.decline.code == "no_documents"
```

Replace `test_an_archived_only_learner_is_409_before_any_agent_call` with:

```python
def test_an_archived_only_learner_gets_the_upload_request_from_the_agent() -> None:
    seen: list[httpx.Request] = []
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    document_id = ingest_ready(library, "ada", "Attention weighs tokens.")
    library.state.documents[document_id].archived = True
    services = api_services(library, threads=threads, agent=fake_agent(recording(seen, sse_no_documents)))
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and "event: decline" in response.text and len(seen) == 1
```

Replace `test_a_question_without_ready_documents_is_409_before_any_agent_call` with:

```python
def test_a_question_in_a_thread_without_ready_documents_streams_the_upload_request_under_its_history() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen, sse_no_documents), ready_document=False)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId("ada"), FixedClock().now(), "T")
    threads.threads[thread.thread_id] = thread
    threads.add_turn(Turn(ThreadId(thread.thread_id), UserId("ada"), "Earlier?", "Earlier answer.", (), None, FixedClock().now()), [])

    response = client.post(f"/threads/{thread.thread_id}/questions", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and len(seen) == 1 and "event: decline" in response.text
    turns = threads.turns(ThreadId(thread.thread_id), UserId("ada"))
    assert [t.question for t in turns] == ["Earlier?", "What is attention?"]
    assert turns[1].decline is not None and turns[1].decline.code == "no_documents"
```

Add `Turn` to the `smart_tutor.tutoring.application` import. If `InMemoryThreads.add_turn` takes a different signature, read `backend/tests/fakes/tutoring.py` and call it as the fake defines it (the port is `ThreadRepository.add_turn(turn, document_ids)`).

Then check the OpenAPI test `test_openapi_names_the_operation_and_declares_the_event_stream` (and any other test that asserts a 409 description for `ask_in_new_thread`): `ask_in_new_thread` must no longer declare 409; `ask_in_thread` declares 409 as "The conversation is archived." Update those assertions to match.

- [ ] **Step 2: Update the service and knowledge tests**

In `backend/tests/unit/tutoring/test_conversation_service.py`: remove `NoDocumentsError` from the import; delete `test_a_learner_without_documents_cannot_start_a_thread`, `test_a_processing_document_is_not_enough_to_start_a_thread`, and `test_an_archived_only_learner_cannot_start_a_thread`; add:

```python
def test_a_thread_starts_without_ready_documents_so_the_upload_request_is_kept() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    document_id = ingest_ready(library, "ada", "Attention is all you need.")
    library.state.documents[document_id].archived = True  # the agent answers with the upload request (US-3)

    thread = service(library, threads, FixedClock()).start_thread(UserId("ada"), "What is attention?")

    assert threads.threads == {thread.thread_id: thread}
```

Drop imports that become unused (`UploadService`, `FakeObjectStore`, `TEST_LIMITS`, `TEST_UPLOAD_LIMITS`, `APP_TZ` are still used by `test_a_thread_starts_only_from_the_learners_ready_active_document`; let ruff tell you).

In `backend/tests/unit/knowledge/test_document_service.py`: delete `test_has_ready_documents_ignores_archived_and_unfinished_documents`; in `test_archived_documents_leave_my_subjects_ready_check_and_duplicate_check` rename it `test_archived_documents_leave_my_subjects_and_the_duplicate_check` and delete the `has_ready_documents` assertion line.

- [ ] **Step 3: Write the isolation tests**

In `backend/tests/isolation/test_threads.py`, replace `test_a_learner_without_documents_starts_no_thread_even_when_another_has_documents_in_their_subject` with:

```python
def test_a_learner_without_documents_asks_with_their_own_token_even_when_another_has_documents() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=(SHARED,))
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers(request)

    services = api_services(library, threads=threads, agent=fake_agent(record))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    response = client.post("/threads", json={"question": "What is attention?"}, headers=B)

    # The agent searches as B (MCP's can_read gives B an empty readable set); the thread is B's, never A's.
    assert response.status_code == 200
    assert [r.headers["authorization"] for r in seen] == ["Bearer token-b"]
    [thread] = threads.threads.values()
    assert thread.user_id == "learner-b"
```

Add a test that a citation never resolves through another learner's document (add `import json` at the top):

```python
def test_a_citation_to_another_learners_document_never_resolves() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    b_document = ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    citation = {"n": 1, "chunk_id": "c1", "document_id": str(b_document), "document_title": "B's paper", "page": 1}
    body = (
        b'event: delta\ndata: {"text": "Hi [1]"}\n\n'
        + f"event: citations\ndata: {json.dumps({'citations': [citation]})}\n\n".encode()
        + b"event: done\ndata: {}\n\n"
    )
    agent = fake_agent(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    services = api_services(library, threads=threads, agent=agent)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    [turn] = client.get(f"/threads/{thread.thread_id}/turns", headers=A).json()

    # Resolved through A's library only: B's document reads as gone, with none of its title or state.
    assert turn["citations"][0]["document_title"] == "Deleted document"
    assert turn["citations"][0]["deleted"] is True and turn["citations"][0]["archived"] is False
    assert library.state.documents[b_document].file_name not in json.dumps(turn)
```

In `backend/tests/isolation/test_search.py` add:

```python
async def test_an_archived_only_learner_gets_an_empty_readable_set_while_another_has_documents() -> None:
    library, verifier, a_doc = world()
    library.state.documents[a_doc].archived = True  # type: ignore[index]

    for arguments in ({"query": A_TEXT}, {"query": B_TEXT}, {"query": A_TEXT, "document_ids": [a_doc]}):
        result = await search_as(library, verifier, "token-a", **arguments)
        assert not result.is_error
        assert result.structured_content["chunks"] == []
```

(`world()` returns `a_doc` as `str`; `library.state.documents` is keyed by `DocumentId`, a `NewType` of `str`, so indexing with the string works — drop the `type: ignore` if mypy doesn't need it.)

- [ ] **Step 4: Run the tests to see them fail**

Run (from `backend/`): `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/unit/tutoring/test_conversation_service.py tests/isolation -q`
Expected: FAIL — the new route tests get 409, the new service test raises `NoDocumentsError`, the isolation thread test gets 409. (The search isolation test and the citation isolation test may already pass: they pin behavior that exists.)

- [ ] **Step 5: Implement**

`backend/src/smart_tutor/apps/api/routes/threads.py`:
- Module docstring: append the sentence `A learner with no ready, non-archived document still gets a stream: the agent's request to upload a document (a "no_documents" decline), kept as a turn like any decline (US-3, US-10).`
- `SSE_RESPONSE`: delete the `409` entry.
- `ASK_IN_THREAD_RESPONSE`: the `409` description becomes `"The conversation is archived."`.
- Remove `NoDocumentsError` from the `smart_tutor.tutoring.application` import.
- `ask_in_new_thread`: delete the `require_documents` try/except block (the first four lines of the body); in `start()`, change `except (NoDocumentsError, DocumentNotAvailableError) as e:` to `except DocumentNotAvailableError as e:`.
- `ask_in_thread`: delete the `await run_in_threadpool(conversations.require_documents, principal.user_id)` line and change `except (NoDocumentsError, ThreadArchivedError) as e:` to `except ThreadArchivedError as e:`.

`backend/src/smart_tutor/tutoring/application/conversation_service.py`: delete `require_documents` and its call in `start_thread`; remove `NoDocumentsError` from the imports; the `start_thread` docstring becomes:

```python
        """A new thread owned by the learner, persisted; its title starts as the first question. Started from a
        document (US-4c), it lists that document as added by the learner; answers still search all documents. A
        learner without ready documents gets a thread too: its turn is the agent's request to upload one (US-3)."""
```

`backend/src/smart_tutor/tutoring/domain/errors.py`: delete the `NoDocumentsError` class. `backend/src/smart_tutor/tutoring/application/__init__.py`: remove it from the import and `__all__`.

`backend/src/smart_tutor/knowledge/application/document_service.py`: delete `has_ready_documents`.

Run `grep -rn "NoDocumentsError\|require_documents\|has_ready_documents" backend/src backend/tests` — expected: no matches.

- [ ] **Step 6: Run the tests to see them pass**

Run (from `backend/`): `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Regenerate the web client**

The OpenAPI responses changed. From `backend/`: `uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json`, then from `web/`: `npm --prefix tools/api-gen ci && npm run api:generate`. Expected: `git diff --stat web/src/api` shows only `openapi.json` and generated files. Then from `web/`: `npm run build` — expected: PASS (the web's own `NoDocumentsError` is untouched until Task 3).

- [ ] **Step 8: Full checks and commit**

Run the backend checks from Global Constraints. Then:

```bash
git add backend web/src/api/openapi.json web/src/api/generated
git commit -m "Stream the upload request to a learner without ready documents" -m "US-3, US-10 (#111): a learner whose documents are all archived or deleted keeps their conversations and gets the agent's upload request instead of a 409, so the request is kept in the conversation's history like any decline. The API no longer checks for ready documents itself; MCP search's can_read decides, as PRD §9.3 step 4 says.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The chat shows the upload request inline, under the history

**Files:**
- Modify: `web/src/api/chat.ts` (decline code type, remove `NO_DOCUMENTS` / `NoDocumentsError`, 409 handling)
- Modify: `web/src/features/chat/ChatPage.tsx`
- Test: `web/src/api/chat.test.ts`, `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: SSE `decline` with code `"limited"` or `"no_documents"` (Tasks 1–2); `TurnResponse.decline` `{code: string, message: string} | null` from history.
- Produces: `export type DeclineCode = "limited" | "no_documents"` in `web/src/api/chat.ts`; `ChatEvent`'s decline is `{ type: "decline"; code: DeclineCode; message: string }`.

Before writing UI, read `DESIGN.md` (compact density) and render the two states: `make design-shots ROUND=v0.10 STATES="chat-no-active-documents,chat-answer-citations" THEME=both` (first time: `cd web && npx playwright install chromium`; if `make` is missing, run the `design-shots` target's command from the `Makefile` directly). Look at the PNGs in `.design-shots/`. The request is a decline card (same card as the limited decline) with the message, the muted line, and one secondary Upload button. The prototype is a spec, not code to copy: reuse `styles.declineCard`, `styles.muted`, `styles.declineActions`, and `LinkButton`.

- [ ] **Step 1: Write the failing API client tests**

In `web/src/api/chat.test.ts`:
- Remove `NoDocumentsError` from the import.
- Delete the test `rejects with NoDocumentsError carrying the API's message on 409`.
- In every other test, delete the lines `await expect(failure).rejects.not.toBeInstanceOf(NoDocumentsError);`.
- Change `rejects with NoDocumentsError or AskRefusedError on 409 by its message` to only check that a 409 with a detail rejects with `AskRefusedError` carrying it (keep its `refused` half, drop the `none` half), and rename it `rejects with AskRefusedError carrying the detail on 409`.
- Add a test next to the existing decline-parsing test (search the file for `"decline"`; follow how it builds an SSE response — reuse that test's helpers exactly):

```ts
  it("reads a no_documents decline", async () => {
    const { apiClient } = api(() =>
      sse(
        'event: decline\ndata: {"code": "no_documents", "message": "None of your documents can be used right now: they are all archived or deleted."}\n\n' +
          "event: done\ndata: {}\n\n",
      ),
    );
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([
      { type: "decline", code: "no_documents", message: "None of your documents can be used right now: they are all archived or deleted." },
      { type: "done" },
    ]);
  });
```

(If the file's SSE helper is not called `sse`, use the one it has.)

- [ ] **Step 2: Write the failing ChatPage tests**

In `web/src/features/chat/ChatPage.test.tsx`, remove `NoDocumentsError` from the import and add near the top:

```ts
const NO_DOCUMENTS = "None of your documents can be used right now: they are all archived or deleted.";
const UPLOAD_HINT = "Upload a document to get an answer. Your earlier answers stay readable.";
```

Replace the test `switches to the upload prompt when the ask finds no documents` with:

```tsx
  it("shows the agent's upload request inline, with Upload, and keeps the composer", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1" }, { type: "decline", code: "no_documents", message: NO_DOCUMENTS }, { type: "done" }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect(await screen.findByText(NO_DOCUMENTS)).toBeInTheDocument();
    expect(screen.getByText(UPLOAD_HINT)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/library");
    // Not the limited decline's way out, and no error.
    expect(screen.queryByRole("button", { name: "Search all my documents" })).not.toBeInTheDocument();
    expect(screen.queryByText(/couldn't answer/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /question/i })).toBeInTheDocument();
  });
```

In `describe("a conversation at its URL", ...)`, replace `a reopened conversation shows its history even with no ready documents` with these three tests:

```tsx
    it("a reopened conversation shows its history even with no ready documents", async () => {
      renderChat({ loadConversation: conversation([turn()]), loadDocs: async () => [] }, "/chat/t1");
      expect(await screen.findByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "Upload a document first" })).not.toBeInTheDocument();
      expect(screen.getByRole("textbox", { name: /question/i })).toBeEnabled();
    });

    it("with no active documents a question goes to this conversation, under its history", async () => {
      const ask = vi.fn(() => events());
      const askIn = vi.fn(() =>
        events({ type: "thread", thread_id: "t1" }, { type: "decline", code: "no_documents", message: NO_DOCUMENTS }, { type: "done" }),
      );
      renderChat({ loadConversation: conversation([turn()]), loadDocs: async () => [], ask, askIn }, "/chat/t1");
      await screen.findByText("It weighs tokens [1].");
      await userEvent.type(await question(), "What does the clipping range control?");
      await userEvent.click(askButton());
      expect(await screen.findByText(NO_DOCUMENTS)).toBeInTheDocument();
      expect(askIn).toHaveBeenCalledWith("t1", "What does the clipping range control?");
      expect(ask).not.toHaveBeenCalled();
      expect(asked()).toEqual(["You asked: What is attention?", "You asked: What does the clipping range control?"]);
      expect(screen.getByText("It weighs tokens [1].")).toBeInTheDocument();
      expect(location()).toBe("/chat/t1");
      expect(screen.getByRole("link", { name: "Upload" })).toHaveAttribute("href", "/library");
    });

    it("a no_documents decline in the history shows its message, with Upload only on the last turn", async () => {
      const nodocs = turn({ question: "Q?", answer: "", citations: [], decline: { code: "no_documents", message: NO_DOCUMENTS } });
      renderChat({ loadConversation: conversation([nodocs, turn()]) }, "/chat/t1");
      expect(await screen.findByText(NO_DOCUMENTS)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Upload" })).not.toBeInTheDocument();
      expect(screen.queryByText(UPLOAD_HINT)).not.toBeInTheDocument();
    });
```

The existing test `an archived document's history citation says Archived and still opens` covers the Archived citation; keep it.

- [ ] **Step 3: Run the tests to see them fail**

Run (from `web/`): `npx vitest run src/api/chat.test.ts src/features/chat/ChatPage.test.tsx`
Expected: FAIL — the inline request isn't rendered (the decline shows the limited card's "Search all my documents" / or nothing), and `askIn` isn't called in the reopened conversation.

- [ ] **Step 4: Implement the API client**

In `web/src/api/chat.ts`:
- Add `export type DeclineCode = "limited" | "no_documents";` above `ChatEvent`, and use it: `| { type: "decline"; code: DeclineCode; message: string }`; in `toEvent`, `return { type: "decline", ...(payload() as { code: DeclineCode; message: string }) };`.
- Delete `NO_DOCUMENTS` and the `NoDocumentsError` class.
- Change the `AskRefusedError` doc comment to `/** A 409 from an ask (e.g. an archived conversation), or a 404 for a starting document the learner can't use: its message is for the learner. */`.
- In `stream`, the 409 block becomes:

```ts
  if (response?.status === 409) {
    const message = detail(error);
    if (message !== null) throw new AskRefusedError(message);
  }
```

- [ ] **Step 5: Implement the page**

In `web/src/features/chat/ChatPage.tsx`:
- Imports: drop `NoDocumentsError`.
- `Exchange`: replace `declined: string | null;` (and its comment) with:

```ts
  /** A turn the tutor didn't answer: "limited" (the conversation's documents don't cover it) or "no_documents" (nothing
   * can be read: the request to upload a document). */
  decline: { code: string; message: string } | null;
```

- Everywhere `declined` is used, switch to `decline`:
  - in `openConversation`: `decline: t.decline ?? null`;
  - in `answer`: `const asked: Exchange = { question: text, answer: "", citations: [], decline: null };`;
  - in `run`: `else if (event.type === "decline") { updateLast((e) => ({ ...e, decline: { code: event.code, message: event.message } })); if (event.code === "no_documents") setNoDocuments(true); }`
  - in the render: `t.decline != null`, `t.decline === null && showCitations && ...`.
- `submit()`: replace its last two lines with:

```ts
    // A limited conversation keeps its thread, so the limit applies. So does a conversation when the learner has no
    // active documents: there is nothing to start a new one from, and the upload request goes under its history.
    // Otherwise a question starts a new thread.
    const keepThread = threadId !== null && (scope === "listed" || noDocuments);
    void answer(trimmed, keepThread ? threadId : null);
```

- `run`'s `catch`: delete the `NoDocumentsError` branch and its comment, so it starts with `if (error instanceof AskRefusedError) setProblem({ message: error.message });`.
- Render: replace the `t.declined != null ? ( <div className={styles.declineCard}> ... </div> ) : (...)` block so a `no_documents` decline gets its own card, and the limited card reads `t.decline.message`:

```tsx
                      {t.decline?.code === "no_documents" ? (
                        <div className={styles.declineCard}>
                          <p>{t.decline.message}</p>
                          {/* The way out is for the latest question only, as for the limited decline. */}
                          {last && (
                            <>
                              <p className={styles.muted}>Upload a document to get an answer. Your earlier answers stay readable.</p>
                              <div className={styles.declineActions}>
                                <LinkButton to="/library" icon={Upload}>
                                  Upload
                                </LinkButton>
                              </div>
                            </>
                          )}
                        </div>
                      ) : t.decline != null ? (
                        <div className={styles.declineCard}>
                          <p>{t.decline.message}</p>
                          {/* existing limited-decline `last && (...)` block, unchanged */}
                        </div>
                      ) : (
                        t.answer && <p className={styles.answer}>{t.answer}</p>
                      )}
```

- Update the comment above `if (noDocuments && routeThreadId === undefined)` to: `// A conversation opened from its URL shows its history even without ready documents; a question there gets the upload request under it.`
- The page header comment block above `export function ChatPage` ends with: add the sentence `With no active documents, a question in a conversation stays in it too (US-10).`

- [ ] **Step 6: Run the tests to see them pass**

Run (from `web/`): `npx vitest run` then `npm run build`
Expected: PASS for both. `grep -rn "NoDocumentsError\|NO_DOCUMENTS\b\|declined" web/src --include=*.ts --include=*.tsx` — expected: only the test file's `NO_DOCUMENTS` constant.

- [ ] **Step 7: Look at it**

Render the page states the tests cover against the mockup PNGs from the step above (run the app or rely on the design shots) and fix any spacing that doesn't match DESIGN.md (compact density). Per the project's memory, check in the installed Chrome too if you open the app in a browser.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/chat.ts web/src/api/chat.test.ts web/src/features/chat/ChatPage.tsx web/src/features/chat/ChatPage.test.tsx
git commit -m "Show the upload request under a conversation's history" -m "US-10 (#111), mockup chat-no-active-documents@v0.10: with every document archived or deleted, a question in a reopened conversation is asked in that conversation, so its history stays readable above the tutor's request to upload a document, with Upload. The API no longer answers 409 for this, so the client's NoDocumentsError is gone.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Record the behavior in the PRD and module docs

**Files:**
- Modify: `sdd/prd.md` (status line version, new "Changes from v2.36" row, §9.3 step 4 wording)
- Modify: `backend/src/smart_tutor/tutoring/README.md`
- Modify: `backend/src/smart_tutor/knowledge/README.md`

- [ ] **Step 1: PRD**

- Status line: `Draft v2.36` → `Draft v2.37`.
- Insert a row directly above `| **Changes from v2.35** |`:

```markdown
| **Changes from v2.36** | No active documents left (#111, US-3, US-10): `POST /threads` and `POST /threads/{id}/questions` no longer answer `409` when the learner has no ready, non-archived document. The agent's search finds an empty readable set (a limited conversation that finds nothing checks the whole library with one more search, k = 1, so it gets the upload request only when nothing at all is readable) and streams `decline` {"code": "no_documents", "message"} then `done` without calling the model; the turn is kept like any decline, so the conversation's history shows it. In a conversation opened at its URL, a learner with no active documents asks in that conversation rather than a new one, so the request sits under the history, with **Upload** (to the Library). The fixed "I couldn't find anything about that in your documents." answer is removed. Old citations to an archived document still open and are marked "Archived". |
```

- §9.3 step 4: replace `the agent turns it into the US-3 request to upload a document (no error is shown to the learner).` with `the agent turns it into the US-3 request to upload a document, a "no_documents" decline kept as the turn (no error is shown to the learner).`

- [ ] **Step 2: Module READMEs**

`backend/src/smart_tutor/tutoring/README.md`, "Built so far": replace `` `ConversationService.require_documents` / `start_thread(user_id, question)` (a learner with no ready, non-archived document gets "Upload a document first"; the title starts as the first question) `` with `` `ConversationService.start_thread(user_id, question)` (the title starts as the first question; a learner with no ready, non-archived document gets a thread too, whose turn is the agent's `no_documents` decline, `NO_DOCUMENTS_DECLINE`) ``. In the same paragraph, after `covers` and `LIMITED_DECLINE (...)`, nothing else changes.

`backend/src/smart_tutor/knowledge/README.md`: remove `has_ready_documents` from the `DocumentService` list in **Key classes**, remove `` `has_ready_documents`, `` from the "callers that need active documents ... filter explicitly" list in **Rules**, and delete the sentence `` `DocumentService.has_ready_documents` says whether the learner has any ready, non-archived document (a thread needs one). ``

- [ ] **Step 3: Check and commit**

Run `grep -rn "Upload a document first\|has_ready_documents\|require_documents\|NO_CHUNKS_ANSWER" backend sdd/prd.md CONTEXT.md` — expected: only historical PRD change rows and the web's full-page "Upload a document first" heading (which stays, at `/chat`).

```bash
git add sdd/prd.md backend/src/smart_tutor/tutoring/README.md backend/src/smart_tutor/knowledge/README.md
git commit -m "Record the upload request for a learner with no active documents (PRD v2.37)" -m "Product behavior changed in #111: the ask endpoints no longer refuse with 409, and the agent's no_documents decline is kept in the conversation's history.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
