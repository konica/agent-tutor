"""Agent HTTP server (internal ClusterIP): POST /ask and POST /resume stream one answer as SSE (PRD §9.2, ADR 0007).

Events, each ``event: <name>\\ndata: <json>\\n\\n``. /ask: ``subjects`` {"subject_ids"} first (the thread's 1–3
subjects), then ``delta`` {"text"} in order, then ``citations`` once
({"citations": [{"n", "chunk_id", "document_title", "page"}]}, ``n`` being the answer's ``[n]`` marker), then
``done``; or, when detection is unsure, ``choose_subjects`` {"subject_ids": [the choices]} then ``done`` (the question
waits in the checkpointer); or ``error`` {"code": "unauthenticated" | "unavailable", "message"}, which ends the
stream and may come before ``subjects``.

/resume {"thread_id", "subject_ids"} answers the waiting question with the learner's pick: ``subjects`` (the picked
ids), ``delta``*, ``citations``, ``done``; 409 before streaming when nothing waits; an invalid pick is ``error``
"unavailable" and the question keeps waiting. Checkpoints are keyed ``<user id>/<thread id>`` from the verified token.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from uuid import UUID

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.agent.graph import AskGraph, build_graph
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.knowledge.application import MAX_SEARCH_SUBJECTS
from smart_tutor.shared.adapters.auth.bearer import BearerToken, CurrentPrincipal
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.adapters.aws.clients import ssm_client
from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.adapters.postgres.checkpointer import open_checkpointer
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.ports.token_verifier import TokenVerifier
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import MAX_SUBJECTS, load_detection_policy

logger = logging.getLogger(__name__)

SIGN_IN_AGAIN = "Please sign in again"
UNAVAILABLE = "The tutor couldn't answer right now. Try again in a moment."
# Proxies must pass each event on as it comes, and nothing may cache the answer.
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
STREAM_MODES: list[Literal["messages", "updates"]] = ["messages", "updates"]


class SubjectIn(BaseModel):
    subject_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID
    question: str = Field(min_length=1, max_length=4000)
    learner_subjects: list[SubjectIn] = Field(min_length=1, max_length=MAX_SEARCH_SUBJECTS)


class ResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    thread_id: UUID
    subject_ids: list[str] = Field(min_length=1, max_length=MAX_SUBJECTS)


def checkpoint_config(user_id: str, thread_id: UUID) -> RunnableConfig:
    """One checkpoint key per learner and thread; the user id comes from the verified token, never the body."""
    return {"configurable": {"thread_id": f"{user_id}/{thread_id}"}}


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def unavailable_events() -> AsyncIterator[str]:
    yield sse("error", {"code": "unavailable", "message": UNAVAILABLE})


async def answer_events(
    graph: AskGraph, graph_input: AskState | Command[Any], config: RunnableConfig, token: str
) -> AsyncIterator[str]:
    streamed = False
    try:
        async for part in graph.astream(
            graph_input, config, context=AgentContext(access_token=token), stream_mode=STREAM_MODES, version="v2"
        ):
            if part["type"] == "updates" and "__interrupt__" in part["data"]:
                pause = part["data"]["__interrupt__"][0]
                yield sse("choose_subjects", {"subject_ids": pause.value["subject_ids"]})
            elif part["type"] == "messages":
                chunk, meta = part["data"]
                if meta.get("langgraph_node") == "answer" and chunk.text:
                    streamed = True
                    yield sse("delta", {"text": chunk.text})
            elif part["type"] == "updates" and "resolve_subjects" in part["data"]:
                if subject_ids := part["data"]["resolve_subjects"]["subject_ids"]:  # empty: waiting for the pick
                    yield sse("subjects", {"subject_ids": subject_ids})
            elif part["type"] == "updates" and "choose_subjects" in part["data"]:
                yield sse("subjects", {"subject_ids": part["data"]["choose_subjects"]["subject_ids"]})
            elif part["type"] == "updates" and "answer" in part["data"]:
                update = part["data"]["answer"]
                if not streamed:  # the fixed no-chunks answer never went through the model
                    yield sse("delta", {"text": update["answer"]})
                citations = [
                    {"n": c.n, "chunk_id": c.chunk_id, "document_title": c.document_title, "page": c.page}
                    for c in update["citations"]
                ]
                yield sse("citations", {"citations": citations})
        yield sse("done", {})
    except UnauthenticatedError as e:
        # Accepted here, refused by the MCP server mid-turn (revoked or expired between hops).
        logger.info("token refused mid-turn: %s", e)  # the reason only, never the token
        yield sse("error", {"code": "unauthenticated", "message": SIGN_IN_AGAIN})
    except Exception:
        logger.exception("ask failed")  # our errors carry no token (McpRetriever keeps it out of messages)
        yield sse("error", {"code": "unavailable", "message": UNAVAILABLE})


def create_app(
    settings: Settings | None = None, verifier: TokenVerifier | None = None, graph: AskGraph | None = None
) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        if not settings.keycloak_client_secret.get_secret_value():
            raise RuntimeError("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET is not set")
        if graph is None:
            model = ModelFactory(settings).chat(ChatRole.AGENT)
            policy = load_detection_policy(
                SsmParameterStore(ssm_client(settings)),
                settings.detect_threshold_param,
                settings.detect_margin_param,
                settings.multi_margin_param,
            )
            async with open_checkpointer(settings.database_url) as saver:
                app.state.graph = build_graph(lambda token: McpRetriever(settings.mcp_url, token), model, policy, saver)
                async with httpx.AsyncClient(timeout=5) as http:
                    app.state.verifier = keycloak_verifier(settings, http)
                    yield
            return
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield

    app = FastAPI(title="Smart Tutor Agent", lifespan=lifespan)
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
        state: AskState = {
            "question": body.question,
            "learner_subjects": {s.subject_id: s.name for s in body.learner_subjects},
        }
        config = checkpoint_config(principal.user_id, body.thread_id)
        return StreamingResponse(
            answer_events(request.app.state.graph, state, config, token),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    @app.post("/resume")
    async def resume(
        body: ResumeRequest, request: Request, token: BearerToken, principal: CurrentPrincipal
    ) -> StreamingResponse:
        graph: AskGraph = request.app.state.graph
        config = checkpoint_config(principal.user_id, body.thread_id)
        pending = (await graph.aget_state(config)).interrupts
        if not pending:
            raise HTTPException(409, "Nothing is waiting for subjects in this thread")
        # Refuse a bad pick before resuming: a pick the node rejects stays in the checkpoint and would be replayed.
        if len(set(body.subject_ids)) != len(body.subject_ids) or not set(body.subject_ids) <= set(
            pending[0].value["subject_ids"]
        ):
            logger.info("resume refused: the pick is not among the choices offered")
            return StreamingResponse(unavailable_events(), media_type="text/event-stream", headers=SSE_HEADERS)
        return StreamingResponse(
            answer_events(graph, Command(resume={"subject_ids": body.subject_ids}), config, token),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return app


app = create_app()
