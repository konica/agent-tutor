"""ModelFactory: builds LangChain chat and embedding models from configuration by role (PRD D15, ADR 0006).

Business code asks for a role and gets a LangChain `BaseChatModel` or `Embeddings`; it never names a model ID.
"""

from enum import StrEnum

from botocore.config import Config
from langchain.chat_models import init_chat_model
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from smart_tutor.shared.adapters.bedrock.nova_embeddings import NovaEmbeddings
from smart_tutor.shared.config import ModelConfig, Settings

# Adaptive mode backs off on ThrottlingException across calls from one client; long answers need a long read timeout.
BOTO_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 4}, connect_timeout=5, read_timeout=120)


class ChatRole(StrEnum):
    AGENT = "agent"
    JUDGE = "judge"


class ModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat(self, role: ChatRole) -> BaseChatModel:
        config: ModelConfig = getattr(self._settings.models, role.value)
        model: BaseChatModel = init_chat_model(
            config.model_id,
            model_provider=config.provider,
            region_name=self._settings.aws_region,
            config=BOTO_CONFIG,
            **config.params,
        )
        return model

    def embedding(self) -> Embeddings:
        config = self._settings.models.embedding
        if config.provider != "bedrock":
            raise ValueError(f"unknown embedding provider {config.provider!r} for {config.model_id}")
        return NovaEmbeddings(
            model_id=config.model_id, region_name=self._settings.aws_region, config=BOTO_CONFIG, **config.params
        )
