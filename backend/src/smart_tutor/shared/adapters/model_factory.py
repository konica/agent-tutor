"""ModelFactory: builds ChatModel / EmbeddingModel adapters from configuration by role (PRD D15).

Business code asks for a role, never a model ID. Bedrock adapters are implemented in M0.
"""

from enum import StrEnum

from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.chat_model import ChatModel
from smart_tutor.shared.ports.embedding_model import EmbeddingModel


class ChatRole(StrEnum):
    AGENT = "agent"
    JUDGE = "judge"


class ModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def chat(self, role: ChatRole) -> ChatModel:
        config = getattr(self._settings.models, role.value)
        raise NotImplementedError(f"M0: build the {config.provider} chat adapter for {config.model_id}")

    def embedding(self) -> EmbeddingModel:
        config = self._settings.models.embedding
        raise NotImplementedError(f"M0: build the {config.provider} embedding adapter for {config.model_id}")
