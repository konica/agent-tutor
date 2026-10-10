"""GitHub Actions deploy access: the account's GitHub OIDC provider and the deploy role (#55).

An admin deploys this stack once from a laptop, because GitHub Actions can't create the role it signs in with.
After that the deploy workflow (#59) updates it like any other stack. Each deployment mode has its own copy (#147):
its own role, trusted by its own GitHub environment. The account's GitHub OIDC provider is the one resource the modes
share (ADR 0015): AWS allows one per URL, so native-cloud's copy creates it and on-premise's imports it.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

from smart_tutor_infra.names import ModeNames

GITHUB_OIDC_HOST = "token.actions.githubusercontent.com"


class GitHubDeployStack(cdk.Stack):
    """The role trusts only jobs in one GitHub environment, which is limited to `main` on GitHub's side.

    It can assume the CDK bootstrap roles (so CloudFormation, not the role, changes infrastructure), push app images
    to its mode's ECR repositories (`<repository prefix>/*`, #206), read its mode's stack outputs, and, with `eks`,
    describe the EKS cluster. With `deploy_document` (on-premise, #150), it runs that one SSM document on the mode's
    instances and reads the result.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        names: ModeNames,
        subject_prefix: str,
        github_environment: str,
        existing_provider_arn: str | None = None,
        eks: bool = False,
        deploy_document: str | None = None,
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
            role_name=names.deploy_role,
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
                resources=[f"arn:aws:ecr:{region}:{account}:repository/{names.repository_prefix}/*"],
            ),
            *(
                [
                    iam.PolicyStatement(
                        sid="EksKubeconfig",
                        actions=["eks:DescribeCluster"],
                        resources=[f"arn:aws:eks:{region}:{account}:cluster/smart-tutor-*"],
                    )
                ]
                if eks
                else []
            ),
            *(
                [
                    # SendCommand is authorized on both the document and the target instance. Only the deploy
                    # document is allowed, so the role can't run arbitrary shell commands on any instance.
                    iam.PolicyStatement(
                        sid="RunDeployDocument",
                        actions=["ssm:SendCommand"],
                        resources=[
                            f"arn:aws:ssm:{region}:{account}:document/{deploy_document}",
                            f"arn:aws:ec2:{region}:{account}:instance/*",
                        ],
                    ),
                    # Neither action supports resource-level permissions.
                    iam.PolicyStatement(
                        sid="ReadDeployStatus",
                        actions=["ssm:DescribeInstanceInformation", "ssm:GetCommandInvocation"],
                        resources=["*"],
                    ),
                ]
                if deploy_document
                else []
            ),
            iam.PolicyStatement(
                sid="ReadStackOutputs",
                actions=["cloudformation:DescribeStacks"],
                resources=[f"arn:aws:cloudformation:{region}:{account}:stack/{names.stack_prefix}-*/*"],
            ),
        ]
        self.deploy_role.attach_inline_policy(
            iam.Policy(self, "DeployPolicy", policy_name="deploy", statements=statements)
        )

        cdk.CfnOutput(self, "DeployRoleArn", value=self.deploy_role.role_arn)
