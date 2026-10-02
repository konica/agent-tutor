"""Documents bucket: uploads/ (presigned POST, expires after 1 day, events -> SQS + DLQ) and contents/<sha256>.pdf
(versioning; tagged unreferenced contents -> Glacier Flexible Retrieval after 30 days), CORS for the web origin (M1)."""

from typing import Any

import aws_cdk as cdk
from constructs import Construct


class StorageStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
