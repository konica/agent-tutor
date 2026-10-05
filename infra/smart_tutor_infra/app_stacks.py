"""Builds every stack for one environment (prod in Releases 1-2; a staging stage can reuse this later)."""

import aws_cdk as cdk

from smart_tutor_infra.stacks.budgets import BudgetsStack
from smart_tutor_infra.stacks.cluster import ClusterStack
from smart_tutor_infra.stacks.config import ConfigStack
from smart_tutor_infra.stacks.data import DataStack
from smart_tutor_infra.stacks.github_deploy import DEPLOY_ROLE_NAME, GitHubDeployStack
from smart_tutor_infra.stacks.network import NetworkStack
from smart_tutor_infra.stacks.registry import RegistryStack
from smart_tutor_infra.stacks.storage import StorageStack


def build_app(app: cdk.App, env_name: str = "prod") -> list[cdk.Stack]:
    env = cdk.Environment(region=app.node.try_get_context("smart-tutor:region") or "us-east-1")
    prefix = f"SmartTutor-{env_name}"
    name = f"smart-tutor-{env_name}"
    network = NetworkStack(app, f"{prefix}-Network", env=env)
    stacks: list[cdk.Stack] = [
        network,
        DataStack(app, f"{prefix}-Data", env=env),
        StorageStack(app, f"{prefix}-Storage", env=env),
        ClusterStack(
            app,
            f"{prefix}-Cluster",
            env=env,
            vpc=network.vpc,
            cluster_name=name,
            admin_principal_arns=app.node.get_context("smart-tutor:eks-admin-principal-arns"),
            deploy_role_name=DEPLOY_ROLE_NAME,
        ),
        RegistryStack(app, f"{prefix}-Registry", env=env),
        ConfigStack(app, f"{prefix}-Config", env=env),
        BudgetsStack(
            app,
            f"{prefix}-Budgets",
            env=env,
            budget_name=f"{name}-monthly",
            monthly_usd=app.node.get_context("smart-tutor:budget-monthly-usd"),
            alert_emails=app.node.get_context("smart-tutor:budget-alert-emails"),
        ),
    ]
    for stack in stacks[1:]:
        stack.add_stack_dependency(network)
    stacks.append(
        GitHubDeployStack(
            app,
            f"{prefix}-GitHubDeploy",
            env=env,
            subject_prefix=app.node.get_context("smart-tutor:github-oidc-subject-prefix"),
            github_environment=app.node.get_context("smart-tutor:github-environment"),
            existing_provider_arn=app.node.try_get_context("smart-tutor:github-oidc-provider-arn"),
        )
    )
    return stacks
