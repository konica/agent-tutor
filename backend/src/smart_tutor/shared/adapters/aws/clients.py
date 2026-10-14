"""boto3 clients.

With settings.localstack, each client calls the endpoint in AWS_ENDPOINT_URL_S3 / AWS_ENDPOINT_URL_SQS /
AWS_ENDPOINT_URL_SSM and signs with LocalStack's dummy keys. Otherwise boto3 resolves endpoints and credentials.
"""

import os
from typing import TYPE_CHECKING, Any

import boto3
from botocore.config import Config

from smart_tutor.shared.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient
    from mypy_boto3_cloudwatch import CloudWatchClient
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_ssm import SSMClient


def _localstack(service: str, settings: Settings) -> dict[str, Any]:
    """LocalStack's endpoint and dummy keys, passed explicitly so real credentials, used for Bedrock, never reach it.

    An explicit endpoint also holds when the shell sets AWS_IGNORE_CONFIGURED_ENDPOINT_URLS (the deploy runbooks do),
    which would otherwise send the dummy keys to real AWS.
    """
    if not settings.localstack:
        return {}
    variable = f"AWS_ENDPOINT_URL_{service.upper()}"
    endpoint = os.environ.get(variable)
    if not endpoint:
        raise RuntimeError(
            f"SMART_TUTOR_LOCALSTACK is on, but {variable} is not set. Start host processes with "
            "`uv run --env-file ../.env`, which sets it to LocalStack (http://localhost:10402)."
        )
    return {"endpoint_url": endpoint, "aws_access_key_id": "test", "aws_secret_access_key": "test"}


def s3_client(settings: Settings) -> "S3Client":
    config = Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.s3_path_style else "auto"})
    return boto3.client("s3", region_name=settings.aws_region, config=config, **_localstack("s3", settings))


def sqs_client(settings: Settings) -> "SQSClient":
    return boto3.client("sqs", region_name=settings.aws_region, **_localstack("sqs", settings))


def ssm_client(settings: Settings) -> "SSMClient":
    return boto3.client("ssm", region_name=settings.aws_region, **_localstack("ssm", settings))


def cloudwatch_client(settings: Settings) -> "CloudWatchClient":
    """Real CloudWatch, also locally: counters are few and content-free."""
    config = Config(connect_timeout=2, read_timeout=2, retries={"mode": "standard", "max_attempts": 2})
    return boto3.client("cloudwatch", region_name=settings.aws_region, config=config)


def bedrock_runtime_client(settings: Settings, config: Config) -> "BedrockRuntimeClient":
    """Real Bedrock (no emulator): for ApplyGuardrail. Model calls go through ModelFactory, never this client."""
    return boto3.client("bedrock-runtime", region_name=settings.aws_region, config=config)
