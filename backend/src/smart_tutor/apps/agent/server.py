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

The request may carry ``thread_id`` and ``run_id`` (set by the API); each ask is traced as one ``ask`` run (PRD §10.4).
"""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.agent.graph import AskGraph, build_graph
from smart_tutor.apps.agent.state import AgentContext, AskState, DeclineCode
from smart_tutor.apps.agent.tracing import AskRun, AskTracing
from smart_tutor.shared.adapters.auth.bearer import BearerToken, CurrentPrincipal
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.adapters.tracing import LearnerHasher, learner_hasher, run_metadata
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.ports.token_verifier import TokenVerifier
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import LIMITED_DECLINE, NO_DOCUMENTS_DECLINE, RetrievedChunk

logger = logging.getLogger(__name__)

SIGN_IN_AGAIN = "Please sign in again"
UNAVAILABLE = "The tutor couldn't answer right now. Try again in a moment."
# Proxies must pass each event on as it comes, and nothing may cache the answer.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
STREAM_MODES: list[Literal["messages", "updates"]] = ["messages", "updates"]
DECLINE_MESSAGES: dict[DeclineCode, str] = {"limited": LIMITED_DECLINE, "no_documents": NO_DOCUMENTS_DECLINE}


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    document_ids: list[str] | None = Field(default=None, max_length=200)
    # Set by the API (PRD §10.4): the conversation and the run id it keeps with the turn. Callers without them
    # (evals) still trace, under a fresh run id.
    thread_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def answer_events(
    graph: AskGraph, body: AskRequest, token: str, run: AskRun, tracing: AskTracing
) -> AsyncIterator[str]:
    state: AskState = {"question": body.question, "document_ids": body.document_ids}
    chunks: list[RetrievedChunk] = []  # what search found; the answer node gives the model exactly these
    answer = ""
    decline: str | None = None
    with tracing.trace(run) as trace:
        try:
            async for part in graph.astream(
                state, context=AgentContext(access_token=token), stream_mode=STREAM_MODES, version="v2"
            ):
                if part["type"] == "messages":
                    chunk, meta = part["data"]
                    if meta.get("langgraph_node") == "answer" and chunk.text:
                        answer += chunk.text
                        yield sse("delta", {"text": chunk.text})
                elif part["type"] == "updates" and "search" in part["data"]:
                    chunks = part["data"]["search"].get("chunks", [])
                elif part["type"] == "updates" and "answer" in part["data"]:
                    update = part["data"]["answer"]
                    if (code := update.get("decline")) is not None:
                        decline = code
                        yield sse("decline", {"code": code, "message": DECLINE_MESSAGES[code]})
                        continue
                    yield sse("sources", {"document_ids": list(dict.fromkeys(c.document_id for c in chunks))})
                    citations = [
                        {
                            "n": c.n,
                            "chunk_id": c.chunk_id,
                            "document_id": c.document_id,
                            "document_title": c.document_title,
                            "page": c.page,
                        }
                        for c in update["citations"]
                    ]
                    yield sse("citations", {"citations": citations})
            trace.finish(answer, decline, len(chunks))
            yield sse("done", {})
        except UnauthenticatedError as e:
            # Accepted here, refused by the MCP server mid-turn (revoked or expired between hops).
            logger.info("token refused mid-turn: %s", e)  # the reason only, never the token
            trace.fail("unauthenticated")
            yield sse("error", {"code": "unauthenticated", "message": SIGN_IN_AGAIN})
        except Exception:
            logger.exception("ask failed")  # our errors carry no token (McpRetriever keeps it out of messages)
            trace.fail("unavailable")
            yield sse("error", {"code": "unavailable", "message": UNAVAILABLE})


def create_app(
    settings: Settings | None = None,
    verifier: TokenVerifier | None = None,
    graph: AskGraph | None = None,
    tracing: AskTracing | None = None,
) -> FastAPI:
    settings = settings or Settings()
    key = settings.learner_hash_key.get_secret_value()
    default_hasher = LearnerHasher(key) if key else None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        hasher = learner_hasher(settings)  # tracing on without a key: refuse to start
        if tracing is None:
            app.state.tracing = AskTracing(run_metadata(settings), hasher)
        if not settings.keycloak_client_secret.get_secret_value():
            raise RuntimeError("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET is not set")
        if graph is None:
            model = ModelFactory(settings).chat(ChatRole.AGENT)
            app.state.graph = build_graph(
                lambda token: McpRetriever(settings.mcp_url, token), model, settings.answer_floor
            )
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield

    app = FastAPI(title="Smart Tutor Agent", lifespan=lifespan)
    app.state.tracing = tracing or AskTracing(run_metadata(settings), default_hasher)
    if verifier is not None:
        app.state.verifier = verifier
    if graph is not None:
        app.state.graph = graph

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/ask")
    async def ask(
        body: AskRequest, request: Request, token: BearerToken, principal: CurrentPrincipal
    ) -> StreamingResponse:
        run = AskRun(
            body.run_id or uuid.uuid4(),
            str(body.thread_id) if body.thread_id else None,
            principal.user_id,
            body.question,
            body.document_ids,
        )
        return StreamingResponse(
            answer_events(request.app.state.graph, body, token, run, request.app.state.tracing),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return app


app = create_app()
