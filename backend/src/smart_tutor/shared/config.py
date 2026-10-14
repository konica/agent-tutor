"""Settings from environment variables (prefix SMART_TUTOR_, nested with __).

Secrets come from Secrets Manager (via External Secrets) in prod.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveInt, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# CloudWatch namespace of the agent's content-free counters (#199); the agent's IAM grant names it (infra).
AGENT_METRICS_NAMESPACE = "SmartTutor/Agent"


class ModelConfig(BaseModel):
    # Chat: an `init_chat_model` provider. Embedding: "bedrock" (NovaEmbeddings).
    provider: str = "bedrock_converse"
    model_id: str
    # Keyword arguments for the LangChain model class (e.g. temperature, max_tokens, dimensions).
    params: dict[str, Any] = {}


class ModelsConfig(BaseModel):
    """Models by role (PRD §9.13). Switching a model is a configuration change gated on the full eval split."""

    agent: ModelConfig = ModelConfig(model_id="us.amazon.nova-2-lite-v1:0")
    # langchain-aws doesn't list Qwen3 as supporting a forced tool choice, but Bedrock accepts it (ADR 0006),
    # and with_structured_output needs it.
    judge: ModelConfig = ModelConfig(
        model_id="qwen.qwen3-32b-v1:0",
        params={"temperature": 0, "supports_tool_choice_values": ["auto", "any", "tool"]},
    )
    embedding: ModelConfig = ModelConfig(
        provider="bedrock", model_id="amazon.nova-2-multimodal-embeddings-v1:0", params={"dimensions": 1024}
    )


class ChunkingConfig(BaseModel):
    """How page text is split into chunks (ADR 0008); `params` go to the method's splitter."""

    method: str = "recursive_character"
    params: dict[str, Any] = {"chunk_size": 1000, "chunk_overlap": 200}


class TopicCheckConfig(BaseModel):
    """The topic check before search (PRD §9.2 step 0, spec 2026-10-13). Off until a model passes the topic_check eval;
    another decision model joins as a new provider (§5.4)."""

    provider: Literal["off", "setfit"] = "off"
    # The SetFit model directory, relative to the working directory: /app/models/topic_check in the agent image,
    # backend/models/topic_check on the host and in CI.
    model_dir: str = "models/topic_check"
    # None: the threshold tuned with the model (its manifest). A number overrides it.
    threshold: float | None = Field(default=None, ge=0, le=1)
    # A slower check fails open: the question goes on to search.
    timeout_ms: PositiveInt = 250


# The agent refuses more than this in an ask request (apps/agent/server.py), so settings may not exceed it.
MAX_HISTORY_TURNS = 20
MAX_HISTORY_ANSWER_CHARS = 8000


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMART_TUTOR_", env_nested_delimiter="__", env_file=".env")

    environment: str = "local"
    # Where this process runs, for traces (PRD §10.4): local (Compose or host), on-premise, or native-cloud (EKS).
    deployment: Literal["local", "on-premise", "native-cloud"] = "local"
    aws_region: str = "us-east-1"
    database_url: str = "postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor"
    keycloak_issuer: str = "http://localhost:10401/realms/smart-tutor"
    keycloak_audience: str = "smart-tutor-api"
    # How services reach Keycloak. In Compose this differs from the issuer the browser sees (ADR 0007).
    keycloak_internal_url: str | None = None
    # This service's confidential client for token introspection: smart-tutor-api (API, agent) or rag-mcp (MCP).
    keycloak_client_id: str = "smart-tutor-api"
    keycloak_client_secret: SecretStr = SecretStr("")
    # HMAC key for the learner hash in traces (PRD §10.4). A secret: <mode prefix>/phoenix/learner-hash-key in Secrets
    # Manager when deployed; required only while tracing is on.
    learner_hash_key: SecretStr = SecretStr("")
    # Runtime traces (PRD §10.4, ADR 0017): the environment's own Phoenix. Spans go to <phoenix_url>/v1/traces; empty
    # leaves the process untraced. http://localhost:10404 on the host, http://phoenix:6006 inside Compose.
    phoenix_url: str = ""
    # Phoenix system key, sent as `authorization: Bearer`: <prefix>/phoenix/api-key when deployed. The local Phoenix
    # has no sign-in, so none locally; a deployed process without it runs untraced.
    phoenix_api_key: SecretStr = SecretStr("")
    # The agent's project; the worker traces into <phoenix_project>-ingestion.
    phoenix_project: str = "smart-tutor-local"
    # Share of traces kept, 0–1 (the SSM parameter trace-sampling-rate when deployed). Outside 0–1 stops startup.
    trace_sampling_rate: float = Field(default=1.0, ge=0, le=1)
    cors_origins: list[str] = ["http://localhost:10453"]
    # Path prefix the API is served under: /api behind CloudFront (ADR 0009). Routes match with and without it.
    root_path: str = ""
    documents_bucket: str = "smart-tutor-documents"
    # LocalStack serves buckets by path (http://localhost:10402/<bucket>); AWS uses virtual-hosted URLs.
    s3_path_style: bool = False
    # S3 and SQS go to LocalStack (AWS_ENDPOINT_URL_*): sign with its dummy keys so real credentials,
    # used for Bedrock, never reach it.
    localstack: bool = False
    ingest_queue_url: str = "http://localhost:10402/000000000000/smart-tutor-ingest"
    mcp_url: str = "http://localhost:10452/mcp"
    # Where the API reaches the agent's POST /ask: http://agent:8080 in Compose.
    agent_url: str = "http://localhost:10451"
    # Port the MCP server listens on: 8000 in containers, 10452 when run on the host (.env).
    mcp_port: int = 8000
    learning_record_idle_minutes_param: str = "/smart-tutor/learning-record-idle-minutes"
    # File limits (PRD §11), read once at startup by the API (presigned POST, GET /uploads/limits) and the worker.
    max_upload_mb_param: str = "/smart-tutor/max-upload-mb"
    max_pages_param: str = "/smart-tutor/max-pages"
    # Seconds the worker lets the PDF parser run per extraction before the document fails (PRD §9.5, worker isolation).
    extraction_timeout_seconds: PositiveInt = 300
    # Processing attempts per content (PRD §9.5), read once at startup by the API.
    max_processing_attempts_param: str = "/smart-tutor/max-processing-attempts"
    # Upload rate limits and daily caps per learner (PRD §11): a rolling hour and a day in app-time-zone, read once at
    # startup by the API.
    max_uploads_per_hour_param: str = "/smart-tutor/max-uploads-per-hour"
    max_uploads_per_day_param: str = "/smart-tutor/max-uploads-per-day"
    # The one app time zone (PRD D27), an IANA name; the API reads it at startup to turn the Library's upload dates
    # into instants. An invalid name stops startup.
    app_time_zone_param: str = "/smart-tutor/app-time-zone"
    rate_limit_per_minute: int = 20
    # Relevance gate for a conversation limited to its documents (US-4c): a best cosine score below it declines.
    # A starting value; US-5 tunes it on the decline dataset and moves it to SSM answer-floor.
    answer_floor: float = 0.3
    # Output tokens one answer may use (US-6), so a question can't buy the model's full 64K-token reply.
    answer_max_tokens: PositiveInt = 1500
    # Conversation history (PRD §9.2 step 3, ADR 0015): a question in an existing conversation sends the agent its
    # last `history_turns` turns (0 sends none), each earlier answer cut to `history_answer_chars` characters.
    history_turns: int = Field(default=5, ge=0, le=MAX_HISTORY_TURNS)
    history_answer_chars: int = Field(default=2000, gt=0, le=MAX_HISTORY_ANSWER_CHARS)
    # Question screen (US-6, #199, PRD D30): "bedrock" sends the learner's question to a Bedrock guardrail before
    # search; a screen that fails or is slower than the timeout lets the question through and is counted.
    question_guard: Literal["off", "bedrock"] = "off"
    question_guardrail_id: str = ""
    question_guardrail_version: str = ""
    question_guard_timeout_seconds: float = Field(default=1.0, gt=0)
    models: ModelsConfig = ModelsConfig()
    chunking: ChunkingConfig = ChunkingConfig()
    topic_check: TopicCheckConfig = TopicCheckConfig()

    @model_validator(mode="after")
    def _question_guard_has_a_guardrail(self) -> "Settings":
        if self.question_guard == "bedrock" and not (self.question_guardrail_id and self.question_guardrail_version):
            raise ValueError(
                "question_guard is bedrock but question_guardrail_id or question_guardrail_version is not set"
            )
        return self

    @property
    def keycloak_introspection_url(self) -> str:
        base = (self.keycloak_internal_url or self.keycloak_issuer).rstrip("/")
        return f"{base}/protocol/openid-connect/token/introspect"
