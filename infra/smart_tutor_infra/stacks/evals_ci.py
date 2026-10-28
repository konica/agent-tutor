"""GitHub Actions access for the smoke evals (#226, #337): the role `evals-smoke.yml` signs in with.

It belongs to neither deployment mode (ADR 0024): `build_app` never builds it, so a mode's `cdk deploy --all` or
teardown can't touch it. An admin deploys it from a laptop (`make evals-ci-deploy`), because GitHub Actions can't
create the role it signs in with, and removes it with `make evals-ci-destroy`. It imports the account's GitHub OIDC
provider by ARN, the one resource ADR 0016 lets stacks share.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

from smart_tutor_infra.models import AGENT_MODEL, AGENT_MODEL_REGIONS, AGENT_PROFILE, EMBEDDING_MODEL, JUDGE_MODEL
from smart_tutor_infra.stacks.github_deploy import GITHUB_OIDC_HOST

STACK_NAME = "SmartTutor-EvalsCI"
ROLE_NAME = "smart-tutor-evals-ci"


class EvalsCiStack(cdk.Stack):
    """The role trusts this repository's pull requests and branch runs (any workflow on any branch, written by anyone
    with push access), so it may do nothing but invoke the models the evals call: the agent model, the embeddings,
    and the judge. That is the bound on its trust; the cost is Bedrock spend."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        subject_prefix: str,
        provider_arn: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        provider = iam.OidcProviderNative.from_oidc_provider_arn(
            self, "GitHubOidc", provider_arn or f"arn:aws:iam::{self.account}:oidc-provider/{GITHUB_OIDC_HOST}"
        )
        self.role = iam.Role(
            self,
            "EvalsRole",
            role_name=ROLE_NAME,
            description="GitHub Actions smoke evals: Bedrock invoke only (#226, #337)",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        f"{GITHUB_OIDC_HOST}:sub": [
                            f"{subject_prefix}:pull_request",
                            f"{subject_prefix}:ref:refs/heads/*",
                        ]
                    },
                },
            ),
        )
        region = self.region
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeEvalModels",
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{region}:{self.account}:inference-profile/{AGENT_PROFILE}",
                    *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
                    f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING_MODEL}",
                    f"arn:aws:bedrock:{region}::foundation-model/{JUDGE_MODEL}",
                ],
            )
        )
        cdk.CfnOutput(self, "RoleArn", value=self.role.role_arn, description="gh secret set EVALS_AWS_ROLE_ARN")
