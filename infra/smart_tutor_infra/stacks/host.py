"""On-premise Host: the VM that runs Smart Tutor with Docker Compose (PRD §9.12). Empty until #148 fills it in.

It references the ECR repositories that native-cloud's RegistryStack owns, rather than creating its own.
"""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from constructs import Construct

from smart_tutor_infra.stacks.registry import SERVICES


class HostStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, services: Sequence[str] = SERVICES, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.repositories = {
            service: ecr.Repository.from_repository_name(
                self, f"{service.capitalize()}Repository", f"smart-tutor/{service}"
            )
            for service in services
        }
        # CloudFormation rejects a template without resources; this free no-op keeps the stack valid until #148.
        cdk.CfnWaitConditionHandle(self, "Placeholder")
