"""LangChain `BedrockEmbeddings` with the Nova request shape the PRD needs (§9.13, ADR 0006).

langchain-aws 1.8 sends `GENERIC_INDEX` for queries too and `truncationMode: END`, which silently drops the end of
a long chunk. This subclass sends `TEXT_RETRIEVAL` for queries and `NONE`, so an oversized chunk fails loudly.
"""

import asyncio
from typing import Any

from langchain_aws import BedrockEmbeddings
from langchain_core.runnables.config import run_in_executor


class NovaEmbeddings(BedrockEmbeddings):
    def _embedding_func(self, text: str, input_type: str = "search_document") -> list[float]:
        params: dict[str, Any] = {
            "embeddingPurpose": "TEXT_RETRIEVAL" if input_type == "search_query" else "GENERIC_INDEX",
            "text": {"truncationMode": "NONE", "value": text},
        }
        if self.dimensions:
            params["embeddingDimension"] = self.dimensions
        body = self._invoke_model(input_body={"taskType": "SINGLE_EMBEDDING", "singleEmbeddingParams": params})
        embeddings = body.get("embeddings")
        if not embeddings or not embeddings[0].get("embedding"):
            raise ValueError("No embedding returned from model")
        return [float(x) for x in embeddings[0]["embedding"]]

    def embed_query(self, text: str) -> list[float]:
        embedding = self._embedding_func(text, input_type="search_query")
        return self._normalize_vector(embedding) if self.normalize else embedding

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        # The base class routes each document through aembed_query, which would embed chunks as queries.
        vectors = await asyncio.gather(*(run_in_executor(None, self._embedding_func, t) for t in texts))
        return [self._normalize_vector(v) if self.normalize else v for v in vectors]
