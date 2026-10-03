"""PROTOTYPE (#29) — throwaway. Agent stand-in: token rides in LangGraph *runtime context*, never state or prompt.

Traces go through the real LangSmith tracer (LangChainTracer) into a recording client instead of the network,
so we can grep exactly what LangSmith would have received. `?leak=1` is a positive control that puts the token
in state on purpose — the leak check must then fire.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, TypedDict

import httpx2
from fastapi import FastAPI, Header, HTTPException
from langchain_core.tracers import LangChainTracer
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langsmith import Client
from mcp import Client as McpClient
from mcp.client.streamable_http import streamable_http_client
from verify import Unauthorized, bearer, verify

MCP_URL = os.environ.get("PROTO_MCP_URL", "http://mcp:8000/mcp")


@dataclass
class AgentContext:
    access_token: str  # per request, not checkpointed, not passed to the model


class State(TypedDict, total=False):
    question: str
    subject_ids: list[str]
    mcp_result: dict[str, Any]
    leaked_token: str  # only set by the ?leak=1 positive control


async def search(state: State, runtime: Runtime[AgentContext]) -> State:
    headers = {"Authorization": f"Bearer {runtime.context.access_token}"}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        McpClient(streamable_http_client(MCP_URL, http_client=http)) as mcp,
    ):
        result = await mcp.call_tool("search", {"query": state["question"], "subject_ids": state["subject_ids"]})
    if result.is_error:
        raise RuntimeError(f"MCP error: {result.content}")
    # A bare `dict` return has no output schema, so the payload arrives as JSON text content.
    return {"mcp_result": result.structured_content or json.loads(result.content[0].text)}


graph = (
    StateGraph(State, context_schema=AgentContext)
    .add_node("search", search)
    .add_edge(START, "search")
    .add_edge("search", END)
    .compile(checkpointer=InMemorySaver())
)


class RecordingClient(Client):
    """LangSmith client that records create/update payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(api_key="proto-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.payloads: list[dict[str, Any]] = []

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "create", **kwargs})

    def update_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "update", "run_id": str(args[0]) if args else None, **kwargs})


app = FastAPI(title="agent-prototype")


@app.post("/invoke")
async def invoke(body: dict[str, Any], authorization: str | None = Header(None), leak: bool = False) -> dict:
    try:
        token = bearer(authorization)
        claims = await verify(token, audience="smart-tutor-api")
    except Unauthorized as e:
        print(f"[agent] 401: {e}", flush=True)
        raise HTTPException(401, "unauthorized") from e
    print(f"[agent] verified sub={claims['sub']}; token -> runtime context", flush=True)

    recorder = RecordingClient()
    tracer = LangChainTracer(client=recorder, project_name="proto-29")
    thread_id = body.get("thread_id", "t1")
    state: State = {"question": body["question"], "subject_ids": body.get("subject_ids", [])}
    if leak:
        state["leaked_token"] = token
    out = await graph.ainvoke(
        state,
        config={"callbacks": [tracer], "configurable": {"thread_id": thread_id}},
        context=AgentContext(access_token=token),
    )
    tracer.wait_for_futures()

    traces = json.dumps(recorder.payloads, default=str)
    checkpoint = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    checkpoint_dump = json.dumps({"values": checkpoint.values, "config": checkpoint.config}, default=str)
    return {
        "state": {k: v for k, v in out.items() if k != "leaked_token"},
        "trace_runs": len(recorder.payloads),
        "trace_bytes": len(traces),
        "token_in_traces": token in traces,
        "token_signature_in_traces": token.rsplit(".", 1)[-1] in traces,
        "token_in_checkpoint": token in checkpoint_dump,
        "trace_sample": recorder.payloads[0] if recorder.payloads else None,
    }
