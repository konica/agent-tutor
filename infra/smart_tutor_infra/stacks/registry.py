"""ECR repositories `smart-tutor/<service>` (#56). The deploy role may push only to these names."""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from constructs import Construct

SERVICES = ("api", "web", "keycloak", "agent", "mcp", "worker")


class RegistryStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, services: Sequence[str] = SERVICES, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Images are rebuilt from git, so a teardown deletes them; a kept repository would block the next deploy.
        self.repositories = {
            service: ecr.Repository(
                self,
                f"{service.capitalize()}Repository",
                repository_name=f"smart-tutor/{service}",
                image_scan_on_push=True,
                lifecycle_rules=[ecr.LifecycleRule(max_image_count=30)],
                removal_policy=cdk.RemovalPolicy.DESTROY,
                empty_on_delete=True,
            )
            for service in services
        }
        cdk.CfnOutput(self, "RegistryUri", value=f"{self.account}.dkr.ecr.{self.region}.amazonaws.com")
