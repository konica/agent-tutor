"""RDS PostgreSQL + pgvector; separate databases for the app and Keycloak (M0)."""

from typing import Any

import aws_cdk as cdk
from constructs import Construct


class DataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
