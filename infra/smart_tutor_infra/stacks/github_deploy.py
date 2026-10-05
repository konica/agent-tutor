"""GitHub Actions deploy access: the account's GitHub OIDC provider and the deploy role (#55).

An admin deploys this stack once from a laptop, because GitHub Actions can't create the role it signs in with.
After that the deploy workflow (#59) updates it like any other stack.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"
DEPLOY_ROLE_NAME = "smart-tutor-github-deploy"


class GitHubDeployStack(cdk.Stack):
    """The role trusts only jobs in one GitHub environment, which is limited to `main` on GitHub's side.

    It can assume the CDK bootstrap roles (so CloudFormation, not the role, changes infrastructure), push app images
    to the `smart-tutor/*` ECR repositories, describe the EKS cluster, and read this app's stack outputs.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        subject_prefix: str,
        github_environment: str,
        existing_provider_arn: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        account, region = cdk.Aws.ACCOUNT_ID, cdk.Aws.REGION

        # One provider per URL per account: import it if something else already created it.
        provider: iam.IOidcProvider = (
            iam.OidcProviderNative.from_oidc_provider_arn(self, "GitHubOidc", existing_provider_arn)
            if existing_provider_arn
            else iam.OidcProviderNative(
                self, "GitHubOidc", url=f"https://{GITHUB_OIDC_HOST}", client_ids=["sts.amazonaws.com"]
            )
        )

        self.deploy_role = iam.Role(
            self,
            "DeployRole",
            role_name=DEPLOY_ROLE_NAME,
            description=f"GitHub Actions (environment {github_environment}) deploys Smart Tutor",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com",
                        f"{GITHUB_OIDC_HOST}:sub": f"{subject_prefix}:environment:{github_environment}",
                    }
                },
            ),
        )
        statements = [
            iam.PolicyStatement(
                sid="AssumeCdkBootstrapRoles",
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{account}:role/cdk-hnb659fds-*-{account}-{region}"],
            ),
            iam.PolicyStatement(sid="EcrLogin", actions=["ecr:GetAuthorizationToken"], resources=["*"]),
            iam.PolicyStatement(
                sid="EcrPushAppImages",
                actions=[
                    "ecr:BatchCheckLayerAvailability",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:InitiateLayerUpload",
                    "ecr:UploadLayerPart",
                    "ecr:CompleteLayerUpload",
                    "ecr:PutImage",
                    "ecr:DescribeImages",
                ],
                resources=[f"arn:aws:ecr:{region}:{account}:repository/smart-tutor/*"],
            ),
            iam.PolicyStatement(
                sid="EksKubeconfig",
                actions=["eks:DescribeCluster"],
                resources=[f"arn:aws:eks:{region}:{account}:cluster/smart-tutor-*"],
            ),
            iam.PolicyStatement(
                sid="ReadStackOutputs",
                actions=["cloudformation:DescribeStacks"],
                resources=[f"arn:aws:cloudformation:{region}:{account}:stack/SmartTutor-prod-*/*"],
            ),
        ]
        self.deploy_role.attach_inline_policy(
            iam.Policy(self, "DeployPolicy", policy_name="deploy", statements=statements)
        )

        cdk.CfnOutput(self, "DeployRoleArn", value=self.deploy_role.role_arn)
