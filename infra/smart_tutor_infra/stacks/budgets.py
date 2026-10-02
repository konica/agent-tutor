"""Bedrock budget alerts (M4)."""

from typing import Any

import aws_cdk as cdk
from constructs import Construct


class BudgetsStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
