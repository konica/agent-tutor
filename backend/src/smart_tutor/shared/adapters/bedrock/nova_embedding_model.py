"""EmbeddingModel over Nova Multimodal Embeddings (synchronous InvokeModel, one text per call; PRD §9.13)."""

import asyncio
import json
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from botocore.exceptions import BotoCoreError, ClientError

from smart_tutor.shared.domain.errors import ModelError, ModelOutputError
from smart_tutor.shared.domain.token_usage import TokenUsage
from smart_tutor.shared.ports.embedding_model import EmbeddingModel, Embeddings

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

SUPPORTED_DIMENSIONS = (256, 384, 1024, 3072)
MAX_CHARACTERS = 8192  # per call; with truncationMode NONE, longer text is an error rather than silently cut
_TOKEN_COUNT_HEADER = "x-amzn-bedrock-input-token-count"

Purpose = Literal["GENERIC_INDEX", "TEXT_RETRIEVAL"]


class NovaEmbeddingModel(EmbeddingModel):
    def __init__(
        self, client: "BedrockRuntimeClient", model_id: str, dimension: int = 1024, max_concurrency: int = 8
    ) -> None:
        if dimension not in SUPPORTED_DIMENSIONS:
            raise ValueError(f"{model_id} supports dimensions {SUPPORTED_DIMENSIONS}, not {dimension}")
        self._client = client
        self._model_id = model_id
        self._dimension = dimension
        self._slots = asyncio.Semaphore(max_concurrency)

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed_documents(self, texts: Sequence[str]) -> Embeddings:
        results = await asyncio.gather(*(self._embed(t, "GENERIC_INDEX") for t in texts))
        usage = sum((u for _, u in results), TokenUsage())
        return Embeddings(vectors=[v for v, _ in results], usage=usage)

    async def embed_query(self, text: str) -> Embeddings:
        vector, usage = await self._embed(text, "TEXT_RETRIEVAL")
        return Embeddings(vectors=[vector], usage=usage)

    async def _embed(self, text: str, purpose: Purpose) -> tuple[list[float], TokenUsage]:
        if not text.strip():
            raise ValueError("cannot embed empty text")
        if len(text) > MAX_CHARACTERS:
            raise ValueError(f"text has {len(text)} characters; {self._model_id} takes at most {MAX_CHARACTERS}")
        body = {
            "taskType": "SINGLE_EMBEDDING",
            "singleEmbeddingParams": {
                "embeddingPurpose": purpose,
                "embeddingDimension": self._dimension,
                "text": {"truncationMode": "NONE", "value": text},
            },
        }
        async with self._slots:
            try:
                response = await asyncio.to_thread(
                    self._client.invoke_model,
                    modelId=self._model_id,
                    body=json.dumps(body),
                    contentType="application/json",
                    accept="application/json",
                )
                payload = json.loads(await asyncio.to_thread(response["body"].read))
            except (ClientError, BotoCoreError) as e:
                raise ModelError(str(e)) from e
        vector = [float(x) for x in payload["embeddings"][0]["embedding"]]
        if len(vector) != self._dimension:
            raise ModelOutputError(f"{self._model_id} returned {len(vector)} dimensions, expected {self._dimension}")
        tokens = int(response["ResponseMetadata"]["HTTPHeaders"].get(_TOKEN_COUNT_HEADER, 0))
        return vector, TokenUsage(input_tokens=tokens)
