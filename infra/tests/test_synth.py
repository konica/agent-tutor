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


def test_all_stacks_synthesize_in_us_east_1() -> None:
    app = make_app()

    stacks = build_app(app)
    assembly = app.synth()

    assert len(stacks) == 9
    assert {s.region for s in stacks} == {"us-east-1"}
    assert len(assembly.stacks) == 9


def test_deploy_role_trusts_only_the_pilot_environment_of_this_repository() -> None:
    t = template(make_app(), "GitHubDeploy")

    t.resource_count_is("AWS::IAM::OIDCProvider", 1)
    t.has_resource_properties(
        "AWS::IAM::OIDCProvider",
        {"Url": "https://token.actions.githubusercontent.com", "ClientIdList": ["sts.amazonaws.com"]},
    )
    t.has_resource_properties(
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
    t = template(make_app(), "GitHubDeploy")

    policies = t.find_resources("AWS::IAM::Policy")
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
    t = template(make_app(**{"smart-tutor:github-oidc-provider-arn": arn}), "GitHubDeploy")

    t.resource_count_is("AWS::IAM::OIDCProvider", 0)
    t.has_resource_properties(
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
                "BudgetLimit": {"Amount": 20, "Unit": "USD"},
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
    assert cluster["Properties"]["ComputeConfig"] == {"Enabled": False}
    assert cluster["Properties"]["UpgradePolicy"] == {"SupportType": "STANDARD"}  # never drift into extended support
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
                            "Condition": {"StringEquals": {"aws:SourceAccount": Match.any_value()}},
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


def test_cluster_deploys_after_the_deploy_role_it_names_in_an_access_entry() -> None:
    stacks = {s.stack_name: s for s in build_app(make_app())}

    assert stacks["SmartTutor-prod-GitHubDeploy"] in stacks["SmartTutor-prod-Cluster"].dependencies


def test_load_balancer_is_internal_and_has_no_internet_ingress() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Name": "smart-tutor-prod", "Scheme": "internal"}
    )
    rendered = json.dumps(t.to_json())
    assert "0.0.0.0/0" not in rendered
    assert "::/0" not in rendered
    t.has_resource_properties(
        "AWS::EC2::SecurityGroup",
        {
            "SecurityGroupIngress": [
                {"IpProtocol": "tcp", "FromPort": 80, "ToPort": 80, "CidrIp": Match.any_value()}
            ],
            "SecurityGroupEgress": [
                {"IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080, "DestinationSecurityGroupId": Match.any_value()}
            ],
        },
    )
    t.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress", {"FromPort": 8080, "SourceSecurityGroupId": Match.any_value()}
    )
    t.has_resource_properties("AWS::ElasticLoadBalancingV2::Listener", {"Port": 80, "Protocol": "HTTP"})


def test_web_target_group_takes_pod_ips_on_8080() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {
            "Name": "smart-tutor-prod-web",
            "TargetType": "ip",
            "Port": 8080,
            "Protocol": "HTTP",
            "HealthCheckPath": "/",
        },
    )
    t.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress", {"FromPort": 8080, "ToPort": 8080, "IpProtocol": "tcp"}
    )
    t.has_output("WebTargetGroupName", {"Value": "smart-tutor-prod-web"})


def test_cloudfront_serves_https_through_a_vpc_origin() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::VpcOrigin",
        {
            "VpcOriginEndpointConfig": Match.object_like(
                {"Name": "smart-tutor-prod", "HTTPPort": 80, "OriginProtocolPolicy": "http-only"}
            )
        },
    )
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "PriceClass": "PriceClass_100",
                    "DefaultCacheBehavior": Match.object_like({"ViewerProtocolPolicy": "redirect-to-https"}),
                    "Origins": [Match.object_like({"VpcOriginConfig": Match.any_value()})],
                }
            )
        },
    )
    t.has_output("CloudFrontUrl", {})
    t.has_output("DistributionId", {})


def test_database_is_private_encrypted_and_kept_as_a_snapshot() -> None:
    t = template(make_app(), "Data")

    t.resource_count_is("AWS::RDS::DBInstance", 1)
    t.has_resource(
        "AWS::RDS::DBInstance",
        {
            "DeletionPolicy": "Snapshot",  # documents and threads are never deleted; teardown keeps a snapshot
            "Properties": Match.object_like(
                {
                    "DBInstanceIdentifier": "smart-tutor-prod",
                    "Engine": "postgres",
                    "EngineVersion": "17",
                    "DBInstanceClass": "db.t4g.micro",
                    "StorageEncrypted": True,
                    "PubliclyAccessible": False,
                    "MultiAZ": False,
                    "BackupRetentionPeriod": 7,
                    "DeletionProtection": False,  # cdk destroy must work
                }
            ),
        },
    )
    t.has_resource_properties("AWS::SecretsManager::Secret", {"Name": "smart-tutor/rds/master"})
    t.has_output("DatabaseEndpoint", {})


def test_database_accepts_postgres_only_from_eks_pods() -> None:
    t = template(make_app(), "Data")

    rendered = json.dumps(t.to_json())
    assert "0.0.0.0/0" not in rendered.replace('"CidrIp": "255.255.255.255/32"', "")
    groups = t.find_resources("AWS::EC2::SecurityGroup")
    ingress = [rule for g in groups.values() for rule in g["Properties"].get("SecurityGroupIngress", [])]
    assert len(ingress) == 1
    assert ingress[0]["FromPort"] == 5432 and ingress[0]["ToPort"] == 5432
    assert "SourceSecurityGroupId" in ingress[0]


def test_app_and_keycloak_get_their_own_generated_database_secrets() -> None:
    t = template(make_app(), "Data")

    for name, user in (("smart-tutor/db/app", "smart_tutor"), ("smart-tutor/db/keycloak", "keycloak")):
        secret = next(
            s for s in t.find_resources("AWS::SecretsManager::Secret").values() if s["Properties"]["Name"] == name
        )
        generate = secret["Properties"]["GenerateSecretString"]
        assert generate["GenerateStringKey"] == "password"
        assert generate["ExcludePunctuation"] is True
        assert generate["PasswordLength"] == 32
        template_text = json.dumps(generate["SecretStringTemplate"])
        assert f'\\"username\\":\\"{user}\\"' in template_text
        assert f'\\"dbname\\":\\"{user}\\"' in template_text
        assert "Endpoint.Address" in template_text  # host comes from the instance


def test_data_deploys_after_the_cluster_whose_pods_it_admits() -> None:
    app = make_app()
    stacks = {s.stack_name: s for s in build_app(app)}
    app.synth()  # cross-stack references add their stack dependencies while synthesizing

    assert stacks["SmartTutor-prod-Cluster"] in stacks["SmartTutor-prod-Data"].dependencies
