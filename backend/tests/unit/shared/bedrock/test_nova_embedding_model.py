"""NovaEmbeddingModel sends one synchronous request per text and reports token usage."""

import json

import pytest

from fakes.bedrock import FakeBedrockClient, embedding_response
from smart_tutor.shared.adapters.bedrock.nova_embedding_model import MAX_CHARACTERS, NovaEmbeddingModel
from smart_tutor.shared.domain.errors import ModelOutputError
from smart_tutor.shared.domain.token_usage import TokenUsage

MODEL_ID = "amazon.nova-2-multimodal-embeddings-v1:0"


def model(client: FakeBedrockClient, dimension: int = 256) -> NovaEmbeddingModel:
    return NovaEmbeddingModel(client, MODEL_ID, dimension=dimension)  # type: ignore[arg-type]


async def test_documents_are_indexed_in_order_and_usage_adds_up() -> None:
    client = FakeBedrockClient([embedding_response([0.1] * 256, tokens=7), embedding_response([0.2] * 256, tokens=5)])

    result = await model(client).embed_documents(["first chunk", "second chunk"])

    assert [v[0] for v in result.vectors] == [0.1, 0.2]
    assert result.usage == TokenUsage(input_tokens=12)
    body = json.loads(client.requests[0]["body"])
    assert client.requests[0]["modelId"] == MODEL_ID
    assert body["taskType"] == "SINGLE_EMBEDDING"
    assert body["singleEmbeddingParams"] == {
        "embeddingPurpose": "GENERIC_INDEX",
        "embeddingDimension": 256,
        "text": {"truncationMode": "NONE", "value": "first chunk"},
    }


async def test_queries_use_the_retrieval_purpose() -> None:
    client = FakeBedrockClient([embedding_response([0.3] * 256)])

    result = await model(client).embed_query("what is the present perfect?")

    assert len(result.vectors) == 1
    assert json.loads(client.requests[0]["body"])["singleEmbeddingParams"]["embeddingPurpose"] == "TEXT_RETRIEVAL"


@pytest.mark.parametrize("text", ["", "   ", "x" * (MAX_CHARACTERS + 1)])
async def test_empty_or_oversized_text_is_rejected_before_calling_bedrock(text: str) -> None:
    client = FakeBedrockClient()

    with pytest.raises(ValueError):
        await model(client).embed_query(text)
    assert client.requests == []


async def test_a_vector_of_the_wrong_size_is_an_output_error() -> None:
    with pytest.raises(ModelOutputError, match="dimensions"):
        await model(FakeBedrockClient([embedding_response([0.1] * 10)])).embed_query("chunk")


def test_unsupported_dimension_fails_fast() -> None:
    with pytest.raises(ValueError, match="dimensions"):
        model(FakeBedrockClient(), dimension=1000)
