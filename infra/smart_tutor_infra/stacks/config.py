"""SSM parameters (per-file limits, processing attempts, learning-record idle minutes) and Secrets Manager entries (M0)."""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class ConfigStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Per-file limits and processing attempts (PRD §11, §9.5), read at startup by the API and the worker; change them here, not in code.
        for name, value in (("max-upload-mb", "50"), ("max-pages", "500"), ("max-processing-attempts", "3")):
            ssm.StringParameter(self, f"Param-{name}", parameter_name=f"/smart-tutor/{name}", string_value=value)
