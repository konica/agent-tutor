"""Agent HTTP server (internal ClusterIP): POST /ask streams one answer as SSE (PRD §9.2, ADR 0007).

Events, each ``event: <name>\\ndata: <json>\\n\\n``: ``subjects`` {"subject_ids"} first (the thread's 1–3
subjects), then ``delta`` {"text"} in order, then ``citations`` once
({"citations": [{"n", "chunk_id", "document_title", "page"}]}, ``n`` being the answer's ``[n]`` marker), then
``done``; or ``error`` {"code": "unauthenticated" | "unavailable", "message"}, which ends the stream and may
come before ``subjects``.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.agent.graph import AskGraph, build_graph
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.knowledge.application import MAX_SEARCH_SUBJECTS
from smart_tutor.shared.adapters.auth.bearer import BearerToken, current_principal
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.adapters.aws.clients import ssm_client
from smart_tutor.shared.adapters.aws.ssm_parameters import SsmParameterStore
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.ports.token_verifier import TokenVerifier
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import load_detection_policy

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
    question: str = Field(min_length=1, max_length=4000)
    learner_subjects: list[SubjectIn] = Field(min_length=1, max_length=MAX_SEARCH_SUBJECTS)


def sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def answer_events(graph: AskGraph, body: AskRequest, token: str) -> AsyncIterator[str]:
    state: AskState = {
        "question": body.question,
        "learner_subjects": {s.subject_id: s.name for s in body.learner_subjects},
    }
    streamed = False
    try:
        async for part in graph.astream(
            state, context=AgentContext(access_token=token), stream_mode=STREAM_MODES, version="v2"
        ):
            if part["type"] == "messages":
                chunk, meta = part["data"]
                if meta.get("langgraph_node") == "answer" and chunk.text:
                    streamed = True
                    yield sse("delta", {"text": chunk.text})
            elif part["type"] == "updates" and "resolve_subjects" in part["data"]:
                yield sse("subjects", {"subject_ids": part["data"]["resolve_subjects"]["subject_ids"]})
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
            app.state.graph = build_graph(lambda token: McpRetriever(settings.mcp_url, token), model, policy)
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

    @app.post("/ask", dependencies=[Depends(current_principal)])
    async def ask(body: AskRequest, request: Request, token: BearerToken) -> StreamingResponse:
        return StreamingResponse(
            answer_events(request.app.state.graph, body, token), media_type="text/event-stream", headers=SSE_HEADERS
        )

    return app


app = create_app()
