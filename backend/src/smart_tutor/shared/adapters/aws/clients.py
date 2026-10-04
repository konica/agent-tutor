"""boto3 clients. Endpoints come from AWS_ENDPOINT_URL_S3 / AWS_ENDPOINT_URL_SQS (LocalStack) when set."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from smart_tutor.shared.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient


def s3_client(settings: Settings) -> "S3Client":
    config = Config(signature_version="s3v4", s3={"addressing_style": "path" if settings.s3_path_style else "auto"})
    return boto3.client("s3", region_name=settings.aws_region, config=config)


def sqs_client(settings: Settings) -> "SQSClient":
    return boto3.client("sqs", region_name=settings.aws_region)
