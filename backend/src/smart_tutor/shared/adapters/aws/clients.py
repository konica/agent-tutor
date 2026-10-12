"""boto3 clients.

Endpoints come from AWS_ENDPOINT_URL_S3 / AWS_ENDPOINT_URL_SQS / AWS_ENDPOINT_URL_SSM (LocalStack) when set.
"""

from typing import TYPE_CHECKING
from urllib.parse import urlparse

import boto3
from botocore.client import BaseClient
from botocore.config import Config

from smart_tutor.shared.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_ssm import SSMClient


def _dummy_key(settings: Settings) -> str | None:
    return "test" if settings.localstack else None


def _localstack_only[C: BaseClient](client: C, variable: str, settings: Settings) -> C:
    """Stop before LocalStack's dummy keys reach real AWS (UnrecognizedClientException: invalid security token)."""
    endpoint = client.meta.endpoint_url
    host = urlparse(endpoint).hostname or ""
    if settings.localstack and (host == "amazonaws.com" or host.endswith(".amazonaws.com")):
        raise RuntimeError(
            f"SMART_TUTOR_LOCALSTACK is on, but this client would call {endpoint}. Point {variable} at LocalStack "
            "(http://localhost:10402) and unset AWS_IGNORE_CONFIGURED_ENDPOINT_URLS: a value already set in your "
            "shell wins over `uv run --env-file`."
        )
    return client


def s3_client(settings: Settings) -> "S3Client":
    config = Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.s3_path_style else "auto"})
    client = boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=config,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )
    return _localstack_only(client, "AWS_ENDPOINT_URL_S3", settings)


def sqs_client(settings: Settings) -> "SQSClient":
    client = boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )
    return _localstack_only(client, "AWS_ENDPOINT_URL_SQS", settings)


def ssm_client(settings: Settings) -> "SSMClient":
    client = boto3.client(
        "ssm",
        region_name=settings.aws_region,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )
    return _localstack_only(client, "AWS_ENDPOINT_URL_SSM", settings)
