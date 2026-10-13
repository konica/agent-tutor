# One image per deployable, all from the smart_tutor package (spec S1).
#   docker build --target api|agent|mcp|worker -t smart-tutor-<target> backend/
# CronJobs reuse the api image. Only the worker installs the `ingest` extra (pypdf and LangChain text splitters, ADR 0005);
# only the agent installs the `guard` extra (Guardrails AI, ADR 0018) and the `topic` extra (onnxruntime and
# tokenizers) and carries the topic-check model (ADR 0019).

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

FROM base AS deps
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM base AS deps-ingest
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra ingest --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra ingest --no-editable

FROM base AS deps-agent
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra guard --extra topic --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra guard --extra topic --no-editable

FROM python:3.12-slim AS runtime
RUN useradd --uid 10001 --no-create-home app
WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 10001

FROM runtime AS api
COPY --from=deps /app/.venv /app/.venv
EXPOSE 8080
CMD ["uvicorn", "smart_tutor.apps.api.main:app", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime AS agent
COPY --from=deps-agent /app/.venv /app/.venv
COPY models/topic_check /app/models/topic_check
EXPOSE 8080
CMD ["uvicorn", "smart_tutor.apps.agent.server:app", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime AS mcp
COPY --from=deps /app/.venv /app/.venv
EXPOSE 8000
CMD ["python", "-m", "smart_tutor.apps.mcp_server.server"]

FROM runtime AS worker
COPY --from=deps-ingest /app/.venv /app/.venv
CMD ["python", "-m", "smart_tutor.apps.worker.main"]
