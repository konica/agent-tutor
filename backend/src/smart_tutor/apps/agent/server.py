"""Agent HTTP server (internal ClusterIP). Serves the LangGraph graph from ``graph.py`` (M2)."""

from fastapi import FastAPI

app = FastAPI(title="Smart Tutor Agent")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
