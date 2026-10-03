"""A stand-in for the boto3 Bedrock Runtime client: records requests and returns scripted responses."""

import io
import json
from typing import Any

from botocore.exceptions import ClientError


class FakeBedrockClient:
    def __init__(self, responses: list[Any] | None = None) -> None:
        self.responses = list(responses or [])
        self.requests: list[dict[str, Any]] = []

    def _next(self, request: dict[str, Any]) -> Any:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def converse(self, **request: Any) -> Any:
        return self._next(request)

    def converse_stream(self, **request: Any) -> Any:
        return {"stream": iter(self._next(request))}

    def invoke_model(self, **request: Any) -> Any:
        return self._next(request)


def converse_response(content: list[dict[str, Any]], **usage: int) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use" if any("toolUse" in b for b in content) else "end_turn",
        "usage": {"inputTokens": 10, "outputTokens": 5, **usage},
    }


def embedding_response(vector: list[float], tokens: int = 7) -> dict[str, Any]:
    body = json.dumps({"embeddings": [{"embeddingType": "TEXT", "embedding": vector}]}).encode()
    return {
        "body": io.BytesIO(body),
        "ResponseMetadata": {"HTTPHeaders": {"x-amzn-bedrock-input-token-count": str(tokens)}},
    }


def throttled() -> ClientError:
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "Too many requests"}}, "Converse")
