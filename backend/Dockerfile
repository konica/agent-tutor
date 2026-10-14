# One image per deployable, all from the smart_tutor package (spec S1).
#   docker build --target api|agent|agent-jailbreak|mcp|worker -t smart-tutor-<target> backend/
# CronJobs reuse the api image. Only the worker installs the `ingest` extra (pypdf and LangChain text splitters, ADR 0005);
# only the agent installs the `guard` extra (Guardrails AI, ADR 0018) and the `topic` extra (onnxruntime and
# tokenizers) and carries the topic-check model (ADR 0020). Only agent-jailbreak installs the `jailbreak` extra (CPU
# torch, transformers, DetectJailbreak; #200) and carries its models in HF_HOME; CI builds and deploys the plain agent.
# The root pyproject's override of rich>=14.2 lifts the cap that cached-path, a dependency of the validator, puts on it.

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

FROM base AS deps-agent-jailbreak
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra guard --extra topic --extra jailbreak --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra guard --extra topic --extra jailbreak --no-editable

# DetectJailbreak's models at pinned commits (smart_tutor.tutoring.adapters.detect_jailbreak.MODELS); fetch writes the
# Hugging Face cache to <dir>/hub, so HF_HOME is <dir>.
FROM deps-agent-jailbreak AS jailbreak-models
RUN /app/.venv/bin/python -m smart_tutor.tutoring.adapters.detect_jailbreak fetch /models/hf \
 && chmod -R a+rX /models/hf

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

# The agent with the optional local question screen (#200, question_guard=guardrails_ai): torch and about 1.5 GB of
# models, so it needs more memory than the default agent (sdd/reviews/2026-10-14-question-screen-comparison.md).
FROM runtime AS agent-jailbreak
COPY --from=deps-agent-jailbreak /app/.venv /app/.venv
COPY models/topic_check /app/models/topic_check
COPY --from=jailbreak-models /models/hf /app/models/hf
ENV HF_HOME=/app/models/hf HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
EXPOSE 8080
CMD ["uvicorn", "smart_tutor.apps.agent.server:app", "--host", "0.0.0.0", "--port", "8080"]

FROM runtime AS mcp
COPY --from=deps /app/.venv /app/.venv
EXPOSE 8000
CMD ["python", "-m", "smart_tutor.apps.mcp_server.server"]

FROM runtime AS worker
COPY --from=deps-ingest /app/.venv /app/.venv
CMD ["python", "-m", "smart_tutor.apps.worker.main"]
