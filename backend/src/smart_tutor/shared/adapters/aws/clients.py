"""boto3 clients.

Endpoints come from AWS_ENDPOINT_URL_S3 / AWS_ENDPOINT_URL_SQS / AWS_ENDPOINT_URL_SSM (LocalStack) when set.
"""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from smart_tutor.shared.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_ssm import SSMClient


def _dummy_key(settings: Settings) -> str | None:
    return "test" if settings.localstack else None


def s3_client(settings: Settings) -> "S3Client":
    config = Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.s3_path_style else "auto"})
    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=config,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )


def sqs_client(settings: Settings) -> "SQSClient":
    return boto3.client(
        "sqs",
        region_name=settings.aws_region,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )


def ssm_client(settings: Settings) -> "SSMClient":
    return boto3.client(
        "ssm",
        region_name=settings.aws_region,
        aws_access_key_id=_dummy_key(settings),
        aws_secret_access_key=_dummy_key(settings),
    )
