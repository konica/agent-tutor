"""SSM parameters (per-file limits, processing attempts, upload rate limits and daily caps, trace sampling rate), the question-screen guardrail with its parameters (#199), and the Keycloak and trace learner-hash secrets in Secrets Manager (#57, #229)."""

import hashlib
import json
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from smart_tutor_infra.models import GUARDRAIL_PROFILE
from smart_tutor_infra.names import ModeNames

# The app time zone (D27); the on-premise patching window is scheduled in it too.
APP_TIME_ZONE = "Asia/Ho_Chi_Minh"

# The question screen (#199, PRD D30): Bedrock Guardrails' prompt-attack filter on the learner's question only.
# Measured on 2026-10-13 with the benign study-question set: LOW tripped 0 of 364 benign questions, MEDIUM 1.1%, HIGH
# 1.6% (PRD §10.1 allows 1%). Re-measure with backend/evals/measure_question_screen.py before changing it.
# The guardrail below is defined twice: `question_screen_definition` in that file (boto3) must stay identical to this
# CloudFormation definition, or its measurements say nothing about production. The two are separate uv projects.
QUESTION_SCREEN_STRENGTH = "LOW"
# The guard message of PRD D29, also the guardrail's blocked message.
GUARD_MESSAGE = "I can only answer questions about your documents. Rephrase it to ask about their content."


def question_screen_definition(
    stack: cdk.Stack, *, input_strength: str = QUESTION_SCREEN_STRENGTH, input_action: str = "BLOCK"
) -> dict[str, Any]:
    """The guardrail's definition (everything but its name and description): what the version's hash covers."""
    return {
        "blocked_input_messaging": GUARD_MESSAGE,
        "blocked_outputs_messaging": GUARD_MESSAGE,
        "content_policy_config": bedrock.CfnGuardrail.ContentPolicyConfigProperty(
            filters_config=[
                bedrock.CfnGuardrail.ContentFilterConfigProperty(
                    type="PROMPT_ATTACK",
                    input_strength=input_strength,
                    output_strength="NONE",
                    input_action=input_action,
                    input_enabled=True,
                    output_enabled=False,
                )
            ],
            content_filters_tier_config=bedrock.CfnGuardrail.ContentFiltersTierConfigProperty(tier_name="STANDARD"),
        ),
        # The Standard tier runs through a cross-region guardrail profile.
        "cross_region_config": bedrock.CfnGuardrail.GuardrailCrossRegionConfigProperty(
            guardrail_profile_arn=f"arn:aws:bedrock:{stack.region}:{stack.account}:guardrail-profile/{GUARDRAIL_PROFILE}"
        ),
    }


def definition_digest(stack: cdk.Stack, definition: dict[str, Any]) -> str:
    """A short hash of the resolved definition, so any field that changes the draft changes the version."""
    resolved = json.dumps(stack.resolve(definition), sort_keys=True)
    return hashlib.sha256(resolved.encode()).hexdigest()[:12]


class ConfigStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, *, names: ModeNames, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Per-file limits, processing attempts, and upload rate limits and daily caps (PRD §11, §9.5), read at startup by the API and the worker, and the
        # app time zone (D27), read by the API, and the share of runs traced in Phoenix (PRD §10.4: every run), read at deploy time; change them here,
        # not in code.
        for name, value in (
            ("max-upload-mb", "50"),
            ("max-pages", "500"),
            ("max-processing-attempts", "3"),
            ("max-uploads-per-hour", "20"),
            ("max-uploads-per-day", "100"),
            ("app-time-zone", APP_TIME_ZONE),
            ("trace-sampling-rate", "1"),
            # The question screen is on everywhere (#199, PRD D30): the product accepts that Bedrock's own processing
            # p95 (about 420-450 ms, measured 2026-10-13) misses the 300 ms latency target; false positives were 0/364.
            ("question-guard", "bedrock"),
        ):
            ssm.StringParameter(self, f"Param-{name}", parameter_name=f"{names.ssm_path}/{name}", string_value=value)

        definition = question_screen_definition(self)
        guardrail = bedrock.CfnGuardrail(
            self,
            "QuestionScreen",
            name=f"{names.data_prefix}-question-screen",
            description="Screens the learner's question for prompt attacks before search (#199)",
            **definition,
        )
        # A version snapshots the draft when it is created, so its description carries a hash of the whole definition:
        # a changed definition replaces the version and publishes a new one. Retaining the old one keeps it for agents
        # still running with it until the next app deploy points them at the new one.
        version = bedrock.CfnGuardrailVersion(
            self,
            "QuestionScreenVersion",
            guardrail_identifier=guardrail.attr_guardrail_id,
            description=f"definition {definition_digest(self, definition)}",
        )
        version.apply_removal_policy(cdk.RemovalPolicy.RETAIN)
        for name, value in (
            ("question-guardrail-id", guardrail.attr_guardrail_id),
            ("question-guardrail-version", version.attr_version),
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

        # Traces name a learner only by an HMAC of their user id (PRD §10.4); the agent and worker read this key. The
        # Phoenix API key is <prefix>/phoenix/api-key, which the operator creates in Phoenix (runbooks).
        secretsmanager.Secret(
            self,
            "LearnerHashKeySecret",
            secret_name=f"{names.secret_prefix}/phoenix/learner-hash-key",
            description="HMAC key for the learner hash in Phoenix traces",
            generate_secret_string=secretsmanager.SecretStringGenerator(exclude_punctuation=True, password_length=64),
        )
