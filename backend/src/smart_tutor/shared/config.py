"""Settings from environment variables (prefix SMART_TUTOR_, nested with __).

Secrets come from Secrets Manager (via External Secrets) in prod.
"""

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class ModelConfig(BaseModel):
    provider: str = "bedrock"
    model_id: str
    # Chat: temperature, max_tokens, top_p. Embedding: dimension, max_concurrency.
    params: dict[str, float | int | str] = {}
    # Chat only: cache the system prompt (Bedrock prompt caching; cached tokens still count as input).
    prompt_cache: bool = False


class ModelsConfig(BaseModel):
    """Models by role (PRD §9.13). Switching a model is a configuration change gated on the full eval split."""

    agent: ModelConfig = ModelConfig(model_id="us.amazon.nova-2-lite-v1:0", prompt_cache=True)
    judge: ModelConfig = ModelConfig(model_id="qwen.qwen3-32b-v1:0", params={"temperature": 0})
    embedding: ModelConfig = ModelConfig(
        model_id="amazon.nova-2-multimodal-embeddings-v1:0", params={"dimension": 1024}
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SMART_TUTOR_", env_nested_delimiter="__", env_file=".env")

    environment: str = "local"
    aws_region: str = "us-east-1"
    database_url: str = "postgresql+psycopg://smart_tutor:smart_tutor@localhost:5432/smart_tutor"
    keycloak_issuer: str = "http://localhost:8080/realms/smart-tutor"
    keycloak_audience: str = "smart-tutor-api"
    documents_bucket: str = "smart-tutor-documents"
    ingest_queue_url: str = "http://localhost:4566/000000000000/smart-tutor-ingest"
    mcp_url: str = "http://localhost:8000/mcp"
    learning_record_idle_minutes_param: str = "/smart-tutor/learning-record-idle-minutes"
    rate_limit_per_minute: int = 20
    models: ModelsConfig = ModelsConfig()
