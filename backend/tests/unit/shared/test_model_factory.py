"""ModelFactory builds LangChain models by role from configuration."""

import pytest
from langchain_aws import ChatBedrockConverse

from smart_tutor.shared.adapters.bedrock.nova_embeddings import NovaEmbeddings
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import ModelConfig, ModelsConfig, Settings


def test_chat_roles_are_bedrock_converse_models_from_config() -> None:
    factory = ModelFactory(Settings())

    agent, judge = factory.chat(ChatRole.AGENT), factory.chat(ChatRole.JUDGE)

    assert isinstance(agent, ChatBedrockConverse) and isinstance(judge, ChatBedrockConverse)
    assert (agent.model_id, agent.region_name) == ("us.amazon.nova-2-lite-v1:0", "us-east-1")
    assert judge.model_id == "qwen.qwen3-32b-v1:0"
    assert judge.temperature == 0
    assert "tool" in (judge.supports_tool_choice_values or ())  # with_structured_output forces the schema tool


def test_embedding_is_nova_with_the_configured_dimension() -> None:
    embedding = ModelFactory(Settings()).embedding()

    assert isinstance(embedding, NovaEmbeddings)
    assert (embedding.model_id, embedding.dimensions) == ("amazon.nova-2-multimodal-embeddings-v1:0", 1024)


def test_unknown_embedding_provider_is_rejected() -> None:
    models = ModelsConfig(embedding=ModelConfig(provider="openai", model_id="text-embedding-3-small"))

    with pytest.raises(ValueError, match="provider"):
        ModelFactory(Settings(models=models)).embedding()
