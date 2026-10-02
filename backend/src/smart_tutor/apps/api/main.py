"""API server (FastAPI). Routes per module are added under ``routes/``; wiring lives in ``deps.py`` (M3)."""

from fastapi import FastAPI

app = FastAPI(title="Smart Tutor API")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}
