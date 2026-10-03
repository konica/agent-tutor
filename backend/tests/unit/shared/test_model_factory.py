"""ModelFactory builds adapters by role from configuration and rejects configurations it cannot honor."""

import pytest

from smart_tutor.shared.adapters.bedrock.converse_chat_model import BedrockConverseChatModel
from smart_tutor.shared.adapters.bedrock.nova_embedding_model import NovaEmbeddingModel
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import ModelConfig, ModelsConfig, Settings


def test_default_settings_build_every_role() -> None:
    factory = ModelFactory(Settings())

    assert isinstance(factory.chat(ChatRole.AGENT), BedrockConverseChatModel)
    assert isinstance(factory.chat(ChatRole.JUDGE), BedrockConverseChatModel)
    embedding = factory.embedding()
    assert isinstance(embedding, NovaEmbeddingModel)
    assert (embedding.model_id, embedding.dimension) == ("amazon.nova-2-multimodal-embeddings-v1:0", 1024)


def test_unknown_provider_is_rejected() -> None:
    models = ModelsConfig(agent=ModelConfig(provider="openai", model_id="gpt"))

    with pytest.raises(ValueError, match="provider"):
        ModelFactory(Settings(models=models)).chat(ChatRole.AGENT)


def test_unknown_embedding_param_is_rejected() -> None:
    models = ModelsConfig(embedding=ModelConfig(model_id="amazon.nova-2-multimodal-embeddings-v1:0", params={"dim": 3}))

    with pytest.raises(ValueError, match="unsupported embedding params"):
        ModelFactory(Settings(models=models)).embedding()
