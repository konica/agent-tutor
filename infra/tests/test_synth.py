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


def test_load_balancer_admits_cloudfront_origin_facing_traffic() -> None:
    # VPC origin traffic doesn't match the VPC range rule: AWS requires the CloudFront origin-facing prefix list (or
    # CloudFront's own security group) on the origin's security group. Without it no request reached the ALB.
    t = template(make_app(), "Edge")

    (alb_sg,) = t.find_resources("AWS::EC2::SecurityGroup")
    t.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress",
        {
            "GroupId": {"Fn::GetAtt": [alb_sg, "GroupId"]},
            "IpProtocol": "tcp",
            "FromPort": 80,
            "ToPort": 80,
            "SourcePrefixListId": "pl-3b927c52",
        },
    )


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


def test_keycloak_target_group_takes_auth_paths_on_8080() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {
            "Name": "smart-tutor-prod-keycloak",
            "TargetType": "ip",
            "Port": 8080,
            "Protocol": "HTTP",
            "HealthCheckPath": "/auth/realms/smart-tutor/.well-known/openid-configuration",
        },
    )
    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule",
        {
            "Priority": 10,
            "Conditions": [{"Field": "path-pattern", "PathPatternConfig": {"Values": ["/auth/*"]}}],
        },
    )
    t.has_output("KeycloakTargetGroupName", {"Value": "smart-tutor-prod-keycloak"})


def test_cloudfront_sends_auth_to_keycloak_uncached_with_every_method() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": Match.array_with([
                        Match.object_like(
                            {
                                "PathPattern": "/auth/*",
                                "ViewerProtocolPolicy": "redirect-to-https",
                                "AllowedMethods": ["GET", "HEAD", "OPTIONS", "PUT", "PATCH", "POST", "DELETE"],
                                "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
                                # AllViewer: cookies, query strings, Authorization, and the viewer Host reach Keycloak
                                "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                            }
                        )
                    ]),
                }
            )
        },
    )


def test_origin_tells_keycloak_the_viewer_used_https() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "Origins": [
                        Match.object_like(
                            {"OriginCustomHeaders": [{"HeaderName": "Forwarded", "HeaderValue": "proto=https"}]}
                        )
                    ]
                }
            )
        },
    )


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
                    "DBInstanceClass": "db.t3.micro",
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


def test_api_target_group_takes_api_paths_on_8080() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {
            "Name": "smart-tutor-prod-api",
            "TargetType": "ip",
            "Port": 8080,
            "Protocol": "HTTP",
            "HealthCheckPath": "/api/healthz",  # through the root path, as CloudFront calls it
        },
    )
    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::ListenerRule",
        {
            "Priority": 20,
            "Conditions": [
                {"Field": "path-pattern", "PathPatternConfig": {"Values": ["/api/*"]}}
            ],
        },
    )
    t.has_output("ApiTargetGroupName", {"Value": "smart-tutor-prod-api"})


def test_cloudfront_sends_api_uncached_with_every_method() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "CacheBehaviors": Match.array_with(
                        [
                            Match.object_like(
                                {
                                    "PathPattern": "/api/*",
                                    "ViewerProtocolPolicy": "redirect-to-https",
                                    "AllowedMethods": [
                                        "GET",
                                        "HEAD",
                                        "OPTIONS",
                                        "PUT",
                                        "PATCH",
                                        "POST",
                                        "DELETE",
                                    ],
                                    "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
                                    # AllViewer: Authorization reaches the API when caching is off
                                    "OriginRequestPolicyId": "216adef6-5c7f-47e4-b989-5492eafa07d3",
                                }
                            )
                        ]
                    ),
                }
            )
        },
    )


def _policy_for(t: Template, service_account: str) -> list[dict[str, Any]]:
    """The statements of the managed policy on the role associated with `smart-tutor/<service_account>`."""
    assoc = next(
        a for a in t.find_resources("AWS::EKS::PodIdentityAssociation").values()
        if a["Properties"]["Namespace"] == "smart-tutor" and a["Properties"]["ServiceAccount"] == service_account
    )
    role_id = assoc["Properties"]["RoleArn"]["Fn::GetAtt"][0]
    role = t.find_resources("AWS::IAM::Role")[role_id]
    policy_id = role["Properties"]["ManagedPolicyArns"][0]["Ref"]
    return t.find_resources("AWS::IAM::ManagedPolicy")[policy_id]["Properties"]["PolicyDocument"]["Statement"]


def _grants(statements: list[dict[str, Any]]) -> dict[str, str]:
    """action → JSON of its resources, for compact assertions."""
    out: dict[str, str] = {}
    for s in statements:
        actions = s["Action"] if isinstance(s["Action"], list) else [s["Action"]]
        for a in actions:
            out[a] = out.get(a, "") + json.dumps(s["Resource"])
    return out


def test_each_service_gets_only_its_own_s3_sqs_and_bedrock_access() -> None:
    t = template(make_app(), "Cluster")
    api, worker, agent, mcp = (_grants(_policy_for(t, sa)) for sa in ("api", "worker", "agent", "mcp-server"))

    # The API only signs uploads into uploads/ and sends Retry messages; it never reads documents.
    assert "s3:GetObject" not in api and "s3:DeleteObject" not in api
    assert "uploads/*" in api["s3:PutObject"] and "contents/" not in api["s3:PutObject"]
    assert "smart-tutor-ingest" in api["sqs:SendMessage"]
    assert "amazon.nova-2-multimodal-embeddings-v1:0" in api["bedrock:InvokeModel"]
    assert "parameter/smart-tutor/*" in api["ssm:GetParameter"]

    # The worker moves uploads into contents and never deletes a content.
    assert "uploads/*" in worker["s3:GetObject"] and "contents/*" in worker["s3:GetObject"]
    assert "contents/*" in worker["s3:PutObject"] and "uploads/" not in worker["s3:PutObject"]
    assert "uploads/*" in worker["s3:DeleteObject"] and "contents/" not in worker["s3:DeleteObject"]
    for action in ("sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility"):
        assert "smart-tutor-ingest" in worker[action] and "dlq" not in worker[action]
    assert "nova-2-lite" in worker["bedrock:InvokeModel"] and "embeddings" in worker["bedrock:InvokeModel"]

    # The agent only chats; the MCP server only embeds queries.
    assert not any(a.startswith(("s3:", "sqs:")) for a in agent)
    assert "inference-profile/us.amazon.nova-2-lite-v1:0" in agent["bedrock:InvokeModel"]
    for region in ("us-east-1", "us-east-2", "us-west-2"):
        assert f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0" in agent["bedrock:InvokeModel"]
    assert "embeddings" not in agent["bedrock:InvokeModel"]
    assert set(mcp) == {"bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"}
    assert "nova-2-lite" not in mcp["bedrock:InvokeModel"]

    # No wildcard actions or resources on any service.
    for grants in (api, worker, agent, mcp):
        assert not any(a.endswith(":*") or a == "*" for a in grants)
        assert not any(r == '"*"' for r in grants.values())


def test_origin_waits_60_seconds_between_bytes() -> None:
    # Answers stream as SSE without heartbeats; CloudFront's default 30 s would cut a slow one with a 504.
    t = template(make_app(), "Edge")
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {"Origins": [Match.object_like({"VpcOriginConfig": Match.object_like({"OriginReadTimeout": 60})})]}
            )
        },
    )