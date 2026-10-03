"""ModelFactory: builds ChatModel / EmbeddingModel adapters from configuration by role (PRD D15).

Business code asks for a role, never a model ID.
"""

from enum import StrEnum
from functools import cached_property
from typing import TYPE_CHECKING

from smart_tutor.shared.adapters.bedrock.client import bedrock_runtime_client
from smart_tutor.shared.adapters.bedrock.converse_chat_model import BedrockConverseChatModel
from smart_tutor.shared.adapters.bedrock.nova_embedding_model import NovaEmbeddingModel
from smart_tutor.shared.config import ModelConfig, Settings
from smart_tutor.shared.ports.chat_model import ChatModel
from smart_tutor.shared.ports.embedding_model import EmbeddingModel

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient


class ChatRole(StrEnum):
    AGENT = "agent"
    JUDGE = "judge"


class ModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @cached_property
    def _bedrock(self) -> "BedrockRuntimeClient":
        return bedrock_runtime_client(self._settings.aws_region)

    def chat(self, role: ChatRole) -> ChatModel:
        config: ModelConfig = getattr(self._settings.models, role.value)
        _require_bedrock(config)
        return BedrockConverseChatModel(self._bedrock, config.model_id, config.params, config.prompt_cache)

    def embedding(self) -> EmbeddingModel:
        config = self._settings.models.embedding
        _require_bedrock(config)
        unknown = set(config.params) - {"dimension", "max_concurrency"}
        if unknown:
            raise ValueError(f"unsupported embedding params for {config.model_id}: {sorted(unknown)}")
        return NovaEmbeddingModel(
            self._bedrock,
            config.model_id,
            dimension=int(config.params.get("dimension", 1024)),
            max_concurrency=int(config.params.get("max_concurrency", 8)),
        )


def _require_bedrock(config: ModelConfig) -> None:
    if config.provider != "bedrock":
        raise ValueError(f"unknown model provider {config.provider!r} for {config.model_id}")
