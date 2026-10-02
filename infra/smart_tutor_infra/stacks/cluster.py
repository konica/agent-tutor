"""EKS cluster, managed node group, Pod Identity associations (M4)."""

from typing import Any

import aws_cdk as cdk
from constructs import Construct


class ClusterStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
