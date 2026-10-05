"""Settings from environment variables (prefix SMART_TUTOR_, nested with __).

Secrets come from Secrets Manager (via External Secrets) in prod.
"""

from typing import Any

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMART_TUTOR_", env_nested_delimiter="__", env_file=".env")

    environment: str = "local"
    aws_region: str = "us-east-1"
    database_url: str = "postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor"
    keycloak_issuer: str = "http://localhost:10401/realms/smart-tutor"
    keycloak_audience: str = "smart-tutor-api"
    # How services reach Keycloak. In Compose this differs from the issuer the browser sees (ADR 0007).
    keycloak_internal_url: str | None = None
    # This service's confidential client for token introspection: smart-tutor-api (API, agent) or rag-mcp (MCP).
    keycloak_client_id: str = "smart-tutor-api"
    keycloak_client_secret: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:10453"]
    documents_bucket: str = "smart-tutor-documents"
    # LocalStack serves buckets by path (http://localhost:10402/<bucket>); AWS uses virtual-hosted URLs.
    s3_path_style: bool = False
    ingest_queue_url: str = "http://localhost:10402/000000000000/smart-tutor-ingest"
    mcp_url: str = "http://localhost:10452/mcp"
    # Port the MCP server listens on: 8000 in containers, 10452 when run on the host (.env).
    mcp_port: int = 8000
    learning_record_idle_minutes_param: str = "/smart-tutor/learning-record-idle-minutes"
    rate_limit_per_minute: int = 20
    models: ModelsConfig = ModelsConfig()

    @property
    def keycloak_introspection_url(self) -> str:
        base = (self.keycloak_internal_url or self.keycloak_issuer).rstrip("/")
        return f"{base}/protocol/openid-connect/token/introspect"
