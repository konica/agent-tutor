"""NovaEmbeddings sends GENERIC_INDEX for documents, TEXT_RETRIEVAL for queries, and never truncates."""

import io
import json
from typing import Any

from smart_tutor.shared.adapters.bedrock.nova_embeddings import NovaEmbeddings


class StubBedrock:
    """Records InvokeModel bodies and answers with a constant vector."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []

    def invoke_model(self, **request: Any) -> dict[str, Any]:
        self.bodies.append(json.loads(request["body"]))
        return {"body": io.BytesIO(json.dumps({"embeddings": [{"embedding": [0.5] * 4}]}).encode())}


def nova(stub: StubBedrock) -> NovaEmbeddings:
    return NovaEmbeddings(model_id="amazon.nova-2-multimodal-embeddings-v1:0", dimensions=1024, client=stub)


def params(body: dict[str, Any]) -> dict[str, Any]:
    assert body["taskType"] == "SINGLE_EMBEDDING"
    single: dict[str, Any] = body["singleEmbeddingParams"]
    return single


def test_documents_are_indexed_without_truncation() -> None:
    stub = StubBedrock()

    vectors = nova(stub).embed_documents(["first\nchunk", "second chunk"])

    assert vectors == [[0.5] * 4] * 2
    assert params(stub.bodies[0]) == {
        "embeddingPurpose": "GENERIC_INDEX",
        "embeddingDimension": 1024,
        "text": {"truncationMode": "NONE", "value": "first\nchunk"},
    }


def test_queries_use_the_retrieval_purpose() -> None:
    stub = StubBedrock()

    nova(stub).embed_query("when do I use the present perfect?")

    assert params(stub.bodies[0])["embeddingPurpose"] == "TEXT_RETRIEVAL"


async def test_async_documents_are_indexed_not_embedded_as_queries() -> None:
    stub = StubBedrock()

    await nova(stub).aembed_documents(["a", "b", "c"])

    assert [params(b)["embeddingPurpose"] for b in stub.bodies] == ["GENERIC_INDEX"] * 3
    assert (await nova(stub).aembed_query("q")) == [0.5] * 4
    assert params(stub.bodies[-1])["embeddingPurpose"] == "TEXT_RETRIEVAL"
