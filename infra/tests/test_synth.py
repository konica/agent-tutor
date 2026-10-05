import json
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk.assertions import Match, Template

from smart_tutor_infra.app_stacks import build_app

CDK_CONTEXT = json.loads((Path(__file__).parents[1] / "cdk.json").read_text())["context"]


def make_app(**extra_context: Any) -> cdk.App:
    return cdk.App(context={**CDK_CONTEXT, **extra_context})


def template(app: cdk.App, suffix: str) -> Template:
    stack = next(s for s in build_app(app) if s.stack_name == f"SmartTutor-prod-{suffix}")
    return Template.from_stack(stack)


def github_deploy_template(app: cdk.App) -> Template:
    return template(app, "GitHubDeploy")


def test_all_stacks_synthesize_in_us_east_1() -> None:
    app = make_app()

    stacks = build_app(app)
    assembly = app.synth()

    assert len(stacks) == 8
    assert {s.region for s in stacks} == {"us-east-1"}
    assert len(assembly.stacks) == 8


def test_deploy_role_trusts_only_the_pilot_environment_of_this_repository() -> None:
    template = github_deploy_template(make_app())

    template.resource_count_is("AWS::IAM::OIDCProvider", 1)
    template.has_resource_properties(
        "AWS::IAM::OIDCProvider",
        {"Url": "https://token.actions.githubusercontent.com", "ClientIdList": ["sts.amazonaws.com"]},
    )
    template.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "smart-tutor-github-deploy",
            "MaxSessionDuration": 3600,
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": "sts:AssumeRoleWithWebIdentity",
                            "Condition": {
                                "StringEquals": {
                                    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
                                    "token.actions.githubusercontent.com:sub": (
                                        "repo:konica@1114311/agent-tutor@1399048529:environment:pilot"
                                    ),
                                }
                            },
                        }
                    )
                ]
            },
        },
    )


def test_deploy_role_gets_only_the_deployment_permissions() -> None:
    template = github_deploy_template(make_app())

    policies = template.find_resources("AWS::IAM::Policy")
    assert len(policies) == 1
    statements = next(iter(policies.values()))["Properties"]["PolicyDocument"]["Statement"]
    assert [s["Sid"] for s in statements] == [
        "AssumeCdkBootstrapRoles",
        "EcrLogin",
        "EcrPushAppImages",
        "EksKubeconfig",
        "ReadStackOutputs",
    ]
    # Only the ECR login, which has no resource, may use "*".
    assert [s["Sid"] for s in statements if s["Resource"] == "*"] == ["EcrLogin"]
    actions = [a for s in statements for a in ([s["Action"]] if isinstance(s["Action"], str) else s["Action"])]
    assert not [a for a in actions if a.startswith(("iam:", "cloudformation:Create", "cloudformation:Update"))]


def test_an_existing_oidc_provider_is_imported_instead_of_created() -> None:
    arn = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
    template = github_deploy_template(make_app(**{"smart-tutor:github-oidc-provider-arn": arn}))

    template.resource_count_is("AWS::IAM::OIDCProvider", 0)
    template.has_resource_properties(
        "AWS::IAM::Role",
        {"AssumeRolePolicyDocument": {"Statement": [Match.object_like({"Principal": {"Federated": arn}})]}},
    )


def test_network_has_private_subnets_and_one_nat_gateway() -> None:
    t = template(make_app(), "Network")

    t.resource_count_is("AWS::EC2::VPC", 1)
    t.resource_count_is("AWS::EC2::NatGateway", 1)
    t.resource_count_is("AWS::EC2::InternetGateway", 1)  # CloudFront VPC origins require one
    t.resource_count_is("AWS::EC2::Subnet", 4)
    for subnet in t.find_resources("AWS::EC2::Subnet").values():
        assert subnet["Properties"]["MapPublicIpOnLaunch"] is False
    t.has_output("VpcId", {})


def test_registry_has_one_repository_per_service_and_empties_them_on_delete() -> None:
    t = template(make_app(), "Registry")

    repos = t.find_resources("AWS::ECR::Repository")
    names = sorted(r["Properties"]["RepositoryName"] for r in repos.values())
    assert names == [f"smart-tutor/{s}" for s in ["agent", "api", "keycloak", "mcp", "web", "worker"]]
    t.has_resource_properties("AWS::ECR::Repository", {"ImageScanningConfiguration": {"ScanOnPush": True}})
    assert all(r["Properties"]["EmptyOnDelete"] is True for r in repos.values())  # teardown works with images inside
    t.has_output("RegistryUri", {})


def test_budget_alerts_at_80_percent_actual_and_100_percent_forecast() -> None:
    t = template(make_app(), "Budgets")

    t.has_resource_properties(
        "AWS::Budgets::Budget",
        {
            "Budget": {
                "BudgetName": "smart-tutor-prod-monthly",
                "BudgetType": "COST",
                "TimeUnit": "MONTHLY",
                "BudgetLimit": {"Amount": 400, "Unit": "USD"},
            },
            "NotificationsWithSubscribers": [
                {
                    "Notification": Match.object_like({"NotificationType": "ACTUAL", "Threshold": 80}),
                    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "dtrungthao@gmail.com"}],
                },
                {
                    "Notification": Match.object_like({"NotificationType": "FORECASTED", "Threshold": 100}),
                    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "dtrungthao@gmail.com"}],
                },
            ],
        },
    )


LB_POLICY = Path(__file__).parents[1] / "smart_tutor_infra/policies/aws-load-balancer-controller-v3.5.0.json"


def test_cluster_runs_eks_1_36_with_two_small_nodes() -> None:
    t = template(make_app(), "Cluster")

    t.has_resource_properties(
        "AWS::EKS::Cluster",
        {
            "Name": "smart-tutor-prod",
            "Version": "1.36",
            "AccessConfig": Match.object_like(
                {"AuthenticationMode": "API", "BootstrapClusterCreatorAdminPermissions": False}
            ),
        },
    )
    cluster = next(iter(t.find_resources("AWS::EKS::Cluster").values()))
    assert "ComputeConfig" not in cluster["Properties"] or not cluster["Properties"]["ComputeConfig"].get("Enabled")
    t.resource_count_is("AWS::EKS::Nodegroup", 1)
    t.has_resource_properties(
        "AWS::EKS::Nodegroup",
        {
            "NodegroupName": "smart-tutor-prod-default",
            "InstanceTypes": ["t3.large"],
            "AmiType": "AL2023_x86_64_STANDARD",
            "ScalingConfig": {"MinSize": 2, "DesiredSize": 2, "MaxSize": 3},
        },
    )
    t.has_resource_properties("AWS::EKS::Addon", {"AddonName": "eks-pod-identity-agent"})
    t.has_output("ClusterName", {})


def test_admin_and_deploy_role_get_cluster_admin_access_entries() -> None:
    t = template(make_app(), "Cluster")

    entries = t.find_resources("AWS::EKS::AccessEntry")
    principals = [json.dumps(e["Properties"]["PrincipalArn"]) for e in entries.values()]
    assert len(entries) == 2
    assert any("arn:aws:iam::685394474162:user/poweruser" in p for p in principals)
    assert any("role/smart-tutor-github-deploy" in p for p in principals)
    assert all("AmazonEKSClusterAdminPolicy" in json.dumps(e["Properties"]["AccessPolicies"]) for e in entries.values())


def test_add_ons_get_iam_through_pod_identity() -> None:
    t = template(make_app(), "Cluster")

    t.has_resource_properties(
        "AWS::EKS::PodIdentityAssociation",
        {"Namespace": "kube-system", "ServiceAccount": "aws-load-balancer-controller"},
    )
    t.has_resource_properties(
        "AWS::EKS::PodIdentityAssociation", {"Namespace": "external-secrets", "ServiceAccount": "external-secrets"}
    )
    t.has_resource_properties(
        "AWS::IAM::Role",
        {
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Action": ["sts:AssumeRole", "sts:TagSession"],
                            "Principal": {"Service": "pods.eks.amazonaws.com"},
                        }
                    )
                ]
            }
        },
    )
    secrets = json.dumps(t.find_resources("AWS::IAM::ManagedPolicy"))
    assert "secret:smart-tutor/*" in secrets


def test_load_balancer_controller_policy_fits_a_managed_policy() -> None:
    document = json.loads(LB_POLICY.read_text())

    assert len(json.dumps(document, separators=(",", ":"))) <= 6144
    t = template(make_app(), "Cluster")
    policies = [p["Properties"]["PolicyDocument"] for p in t.find_resources("AWS::IAM::ManagedPolicy").values()]
    assert any(len(p["Statement"]) == len(document["Statement"]) for p in policies)
