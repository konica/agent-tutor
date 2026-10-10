"""Builds every stack of one deployment mode for one environment (prod in Releases 1-2; a staging stage can reuse this
later). The mode comes from the context `smart-tutor:mode` (`on-premise` by default, or `native-cloud`; #147)."""

import aws_cdk as cdk

from smart_tutor_infra.names import DEFAULT_MODE, NATIVE_CLOUD, ModeNames, mode_names
from smart_tutor_infra.stacks.budgets import BudgetsStack
from smart_tutor_infra.stacks.cluster import ClusterStack
from smart_tutor_infra.stacks.config import ConfigStack
from smart_tutor_infra.stacks.data import DataStack
from smart_tutor_infra.stacks.edge import EdgeStack
from smart_tutor_infra.stacks.github_deploy import GITHUB_OIDC_HOST, GitHubDeployStack
from smart_tutor_infra.stacks.host import HostStack
from smart_tutor_infra.stacks.network import NetworkStack
from smart_tutor_infra.stacks.registry import RegistryStack
from smart_tutor_infra.stacks.storage import StorageStack

# The GitHub environment whose jobs may assume the on-premise deploy role (deploy-on-premise.yml, #150).
ON_PREMISE_GITHUB_ENVIRONMENT = "on-premise"


def build_app(app: cdk.App, env_name: str = "prod") -> list[cdk.Stack]:
    env = cdk.Environment(region=app.node.try_get_context("smart-tutor:region") or "us-east-1")
    names = mode_names(app.node.try_get_context("smart-tutor:mode") or DEFAULT_MODE, env_name)
    if names.mode == NATIVE_CLOUD:
        return _native_cloud(app, env, names)
    return _on_premise(app, env, names)


def _budgets(app: cdk.App, env: cdk.Environment, names: ModeNames) -> BudgetsStack:
    return BudgetsStack(
        app,
        f"{names.stack_prefix}-Budgets",
        env=env,
        budget_name=f"{names.resource_prefix}-monthly",
        monthly_usd=app.node.get_context("smart-tutor:budget-monthly-usd"),
        alert_emails=app.node.get_context("smart-tutor:budget-alert-emails"),
    )


def _on_premise(app: cdk.App, env: cdk.Environment, names: ModeNames) -> list[cdk.Stack]:
    """Storage, Config, Budgets, GitHubDeploy, and Registry of its own, and the Host; it shares no stack with
    native-cloud (ADR 0015). The Host names its repositories through ModeNames, so it never references the Registry
    stack."""
    prefix = names.stack_prefix
    deploy = GitHubDeployStack(
        app,
        f"{prefix}-GitHubDeploy",
        env=env,
        names=names,
        subject_prefix=app.node.get_context("smart-tutor:github-oidc-subject-prefix"),
        github_environment=ON_PREMISE_GITHUB_ENVIRONMENT,
        deploy_document=names.deploy_document,
        # The account's one GitHub provider already exists (native-cloud's GitHubDeploy created it).
        existing_provider_arn=app.node.try_get_context("smart-tutor:github-oidc-provider-arn")
        or f"arn:aws:iam::{cdk.Aws.ACCOUNT_ID}:oidc-provider/{GITHUB_OIDC_HOST}",
    )
    domain = app.node.try_get_context("smart-tutor:on-premise-domain") or None
    return [
        StorageStack(
            app,
            f"{prefix}-Storage",
            env=env,
            names=names,
            # Storage never references the Host: an export of the Elastic IP would lock the VM's address (no
            # `cdk destroy` of the Host, no switch of the domain). Presigned URLs and policies stay the credential, so
            # the sslip.io wildcard (no domain set) only widens which page origins may read the bucket's responses.
            web_origin=f"https://{domain}" if domain else "https://*.sslip.io",
            backups_retention=cdk.Duration.days(30),
        ),
        ConfigStack(app, f"{prefix}-Config", env=env, names=names),
        _budgets(app, env, names),
        deploy,
        RegistryStack(app, f"{prefix}-Registry", env=env, names=names),
        HostStack(
            app,
            f"{prefix}-Host",
            env=env,
            names=names,
            instance_type=app.node.get_context("smart-tutor:on-premise-instance-type"),
            # The DuckDNS name (#154); empty: <Elastic IP>.sslip.io.
            domain=domain,
            # Empty: a blank data volume. Set only to restore one (docs/runbooks/on-premise-backups.md); clearing it
            # again replaces the restored volume with a blank one.
            data_snapshot_id=app.node.try_get_context("smart-tutor:on-premise-data-snapshot-id") or None,
            # The backup, recovery, uptime, and patching alarms email the budget's recipients (#151, #152).
            alert_emails=app.node.get_context("smart-tutor:budget-alert-emails"),
        ),
    ]


def _native_cloud(app: cdk.App, env: cdk.Environment, names: ModeNames) -> list[cdk.Stack]:
    prefix = names.stack_prefix
    network = NetworkStack(app, f"{prefix}-Network", env=env)
    deploy = GitHubDeployStack(
        app,
        f"{prefix}-GitHubDeploy",
        env=env,
        names=names,
        subject_prefix=app.node.get_context("smart-tutor:github-oidc-subject-prefix"),
        github_environment=app.node.get_context("smart-tutor:github-environment"),
        existing_provider_arn=app.node.try_get_context("smart-tutor:github-oidc-provider-arn"),
        eks=True,
    )
    cluster = ClusterStack(
        app,
        f"{prefix}-Cluster",
        env=env,
        vpc=network.vpc,
        names=names,
        admin_principal_arns=app.node.get_context("smart-tutor:eks-admin-principal-arns"),
    )
    # The cluster's access entry names the deploy role by ARN string, so CloudFormation cannot infer the order.
    cluster.add_stack_dependency(deploy)
    # The cluster security group id makes Data deploy after Cluster; only pods reach the database.
    data = DataStack(
        app,
        f"{prefix}-Data",
        env=env,
        vpc=network.vpc,
        cluster_security_group_id=cluster.cluster_security_group_id,
        name_prefix=names.resource_prefix,
    )
    edge = EdgeStack(
        app,
        f"{prefix}-Edge",
        env=env,
        vpc=network.vpc,
        cluster_security_group_id=cluster.cluster_security_group_id,
        name_prefix=names.resource_prefix,
    )
    stacks: list[cdk.Stack] = [
        network,
        data,
        # The bucket's CORS allows only the CloudFront address, so Storage deploys after Edge.
        StorageStack(app, f"{prefix}-Storage", env=env, names=names, web_origin=edge.public_url),
        cluster,
        RegistryStack(app, f"{prefix}-Registry", env=env, names=names),
        ConfigStack(app, f"{prefix}-Config", env=env, names=names),
        _budgets(app, env, names),
    ]
    for stack in stacks[1:]:
        stack.add_stack_dependency(network)
    stacks.append(deploy)
    stacks.append(edge)
    return stacks
