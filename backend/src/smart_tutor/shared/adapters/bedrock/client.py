"""The one place a Bedrock Runtime client is built: region, timeouts, and retries for throttling."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

# Adaptive mode backs off on ThrottlingException across calls from this client; long answers need a long read timeout.
_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 4}, connect_timeout=5, read_timeout=120)


def bedrock_runtime_client(region: str) -> "BedrockRuntimeClient":
    return boto3.client("bedrock-runtime", region_name=region, config=_CONFIG)
