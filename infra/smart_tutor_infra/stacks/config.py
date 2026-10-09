"""SSM parameters (per-file limits, processing attempts) and the Keycloak secrets in Secrets Manager (#57)."""

import json
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from smart_tutor_infra.names import ModeNames


class ConfigStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, names: ModeNames, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Per-file limits and processing attempts (PRD §11, §9.5), read at startup by the API and the worker, and the
        # app time zone (D27), read by the API; change them here, not in code.
        for name, value in (
            ("max-upload-mb", "50"),
            ("max-pages", "500"),
            ("max-processing-attempts", "3"),
            ("app-time-zone", "Asia/Ho_Chi_Minh"),
        ):
            ssm.StringParameter(self, f"Param-{name}", parameter_name=f"{names.ssm_path}/{name}", string_value=value)

        # Keycloak (#57): the bootstrap admin, and the confidential clients' secrets that the realm import reads.
        secretsmanager.Secret(
            self,
            "KeycloakAdminSecret",
            secret_name=f"{names.secret_prefix}/keycloak/admin",
            description="Keycloak bootstrap admin (master realm)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"username": "admin"}),
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=32,
            ),
        )
        for construct_name, client_id in (("Api", "smart-tutor-api"), ("Mcp", "rag-mcp")):
            secretsmanager.Secret(
                self,
                f"Keycloak{construct_name}ClientSecret",
                secret_name=f"{names.secret_prefix}/keycloak/{construct_name.lower()}-client",
                description=f"Client secret of the confidential Keycloak client {client_id}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    exclude_punctuation=True, password_length=40
                ),
            )
