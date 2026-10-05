# The web app is public at the CloudFront address — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Anyone opens `https://<id>.cloudfront.net` and gets the Smart Tutor app shell served by a `web` pod on EKS, through CloudFront → VPC origin → internal ALB. Sign-in doesn't work yet.

**Architecture:** CDK owns everything AWS: VPC (`NetworkStack`), EKS + node group + access entries + Pod Identity (`ClusterStack`), ECR (`RegistryStack`), budget (`BudgetsStack`), and a new `EdgeStack` with the **internal ALB, its listener, one target group per service, and the CloudFront distribution with a VPC origin**. In the cluster, the AWS Load Balancer Controller only registers pod IPs into the CDK-made target group through a `TargetGroupBinding` that names the group (`smart-tutor-prod-web`). So one `cdk deploy` creates the whole path, with no Ingress-made ALB whose ARN CloudFront would need afterwards. Later slices add `/api/*` and `/auth/*` as listener rules, target groups, and CloudFront behaviors in `EdgeStack`.

**Tech Stack:** aws-cdk-lib 2.272 (`aws_eks_v2`, `aws_cloudfront_origins.VpcOrigin`), EKS 1.36, Helm 3, AWS Load Balancer Controller chart 3.5.0, External Secrets chart 2.11.0, metrics-server chart 3.14.0, Vite/React, nginx-unprivileged.

**Spec:** GitHub issue #56 (parent #54, decisions approved 2026-10-04); PRD §9.11, §9.12, Appendix A; recorded values on #55; `docs/runbooks/pilot-environment-overview.md`.

## Global Constraints

- Names the deploy role's policy depends on: cluster `smart-tutor-prod`, ECR repositories `smart-tutor/<service>`, stacks `SmartTutor-prod-*`, deploy role `smart-tutor-github-deploy`. Region `us-east-1`.
- Resource name prefix `smart-tutor-<env>` (`smart-tutor-prod`): ALB `smart-tutor-prod`, web target group `smart-tutor-prod-web`, budget `smart-tutor-prod-monthly`, node group `smart-tutor-prod-default`, VPC origin `smart-tutor-prod`.
- Context in `infra/cdk.json`: `smart-tutor:eks-admin-principal-arns` = `["arn:aws:iam::685394474162:user/poweruser"]`, `smart-tutor:budget-monthly-usd` = `400`, `smart-tutor:budget-alert-emails` = `["dtrungthao@gmail.com"]` (decided on #55).
- Budget: monthly COST budget, USD 400, email at 80% of ACTUAL and 100% of FORECASTED spend.
- VPC: 2 AZs, CIDR `10.40.0.0/16`, public `/24` subnets (NAT and the internet gateway that VPC origins require; no public IPs on launch), private-with-egress `/20` subnets, exactly 1 NAT gateway.
- EKS: version 1.36, endpoint public and private, managed node group 2× `t3.large` (min 2, max 3, AL2023 x86_64, 30 GiB), no Auto Mode, `eks-pod-identity-agent` add-on; cluster-admin access entries for each admin principal and for the deploy role; the cluster creator gets no automatic admin.
- Pod Identity: `kube-system/aws-load-balancer-controller` → role with the vendored official policy `infra/smart_tutor_infra/policies/aws-load-balancer-controller-v3.5.0.json` (a customer-managed policy, ≤ 6,144 characters minified); `external-secrets/external-secrets` → role allowed `secretsmanager:GetSecretValue` and `DescribeSecret` on `secret:smart-tutor/*`.
- Web port 8080 everywhere (container, target group, security group rules). ALB listener HTTP 80, reachable only from inside the VPC (the CloudFront VPC origin's ENIs). No `0.0.0.0/0` or `::/0` ingress in `EdgeStack`.
- CloudFront: default `*.cloudfront.net` certificate, `redirect-to-https`, managed cache policy *UseOriginCacheControlHeaders*, managed response headers policy *SecurityHeadersPolicy*, price class 100, origin protocol HTTP only (the hop stays on AWS's network inside the VPC origin; the ALB has no certificate because there is no domain).
- Stack outputs later slices consume: `SmartTutor-prod-Edge` → `CloudFrontUrl` (`https://<domain>`), `DistributionId`, `WebTargetGroupName`; `SmartTutor-prod-Network` → `VpcId`; `SmartTutor-prod-Cluster` → `ClusterName`; `SmartTutor-prod-Registry` → `RegistryUri`.
- Web build: `VITE_API_URL=/api`, `VITE_KEYCLOAK_URL=/auth` for the pilot; relative values resolve against `window.location.origin`; an empty or missing value falls back to the local defaults.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd infra && uv run pytest`; `helm lint deploy/helm/smart-tutor` and `helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml`; `cd web && npm run build && npm test`. Set `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1` to silence the Node warning.

## Review Focus

1. **Compose builds the web image with no build args.** An empty `VITE_*` value must fall back to the localhost defaults, not produce `""` URLs. Pinned in Task 4 (`falls back to the local API when VITE_API_URL is empty`).
2. **The web pod runs with a read-only root filesystem.** nginx must still start (writable `/tmp`). Pinned in Task 4 Step 6 (`docker run --read-only --tmpfs /tmp`).
3. **Teardown with images in ECR.** `cdk destroy` must not fail on non-empty repositories. Pinned in Task 1 (`empty_on_delete`, asserted as `EmptyOnDelete: true` on each repository).
4. **The LB controller policy fits a managed policy.** Pinned in Task 2 (`test_load_balancer_controller_policy_fits_a_managed_policy`).
5. **The load balancer is reachable from the internet.** Pinned in Task 3 (`test_load_balancer_is_internal_and_has_no_internet_ingress`).

---

### Task 1: Network, registry, and budget stacks; app wiring

**Files:**
- Modify: `infra/cdk.json`, `infra/smart_tutor_infra/app_stacks.py`, `infra/smart_tutor_infra/stacks/network.py`, `infra/smart_tutor_infra/stacks/registry.py`, `infra/smart_tutor_infra/stacks/budgets.py`
- Test: `infra/tests/test_synth.py`

**Interfaces:**
- Produces: `NetworkStack.vpc: ec2.Vpc`; `RegistryStack(..., services)`; `BudgetsStack(..., budget_name: str, monthly_usd: float, alert_emails: Sequence[str])`; a test helper `template(app, suffix: str) -> Template` that finds the stack named `SmartTutor-prod-<suffix>`.

- [ ] **Step 1: Add context to `infra/cdk.json`**

```json
{
  "app": "uv run python app.py",
  "context": {
    "smart-tutor:region": "us-east-1",
    "smart-tutor:github-oidc-subject-prefix": "repo:konica@1114311/agent-tutor@1399048529",
    "smart-tutor:github-environment": "pilot",
    "smart-tutor:eks-admin-principal-arns": ["arn:aws:iam::685394474162:user/poweruser"],
    "smart-tutor:budget-monthly-usd": 400,
    "smart-tutor:budget-alert-emails": ["dtrungthao@gmail.com"]
  }
}
```

- [ ] **Step 2: Write failing tests** (append to `infra/tests/test_synth.py`; replace `github_deploy_template` with the generic helper and update its callers)

```python
def template(app: cdk.App, suffix: str) -> Template:
    stack = next(s for s in build_app(app) if s.stack_name == f"SmartTutor-prod-{suffix}")
    return Template.from_stack(stack)


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
```

Also change `test_all_stacks_synthesize_in_us_east_1` to expect **9** stacks (Task 3 adds `Edge`; until then the count is 8 — set it to 9 in Task 3, keep 8 here).

- [ ] **Step 3: Run tests — expect the three new tests to FAIL**

Run: `cd infra && uv run pytest -q`

- [ ] **Step 4: Implement `network.py`**

```python
"""VPC in 2 AZs: public subnets hold the NAT gateway and the internet gateway that CloudFront VPC origins require;
private subnets hold the EKS nodes, the internal load balancer, and later RDS (#56)."""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.40.0.0/16"),
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24, map_public_ip_on_launch=False
                ),
                ec2.SubnetConfiguration(name="private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=20),
            ],
        )
        cdk.CfnOutput(self, "VpcId", value=self.vpc.vpc_id)
```

- [ ] **Step 5: Implement `registry.py`**

```python
"""ECR repositories `smart-tutor/<service>` (#56). The deploy role may push only to these names."""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from constructs import Construct

SERVICES = ("api", "web", "keycloak", "agent", "mcp", "worker")


class RegistryStack(cdk.Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, services: Sequence[str] = SERVICES, **kwargs: Any
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Images are rebuilt from git, so a teardown deletes them; a kept repository would block the next deploy.
        self.repositories = {
            service: ecr.Repository(
                self,
                f"{service.capitalize()}Repository",
                repository_name=f"smart-tutor/{service}",
                image_scan_on_push=True,
                lifecycle_rules=[ecr.LifecycleRule(max_image_count=30)],
                removal_policy=cdk.RemovalPolicy.DESTROY,
                empty_on_delete=True,
            )
            for service in services
        }
        cdk.CfnOutput(self, "RegistryUri", value=f"{self.account}.dkr.ecr.{self.region}.amazonaws.com")
```

- [ ] **Step 6: Implement `budgets.py`**

```python
"""Monthly cost budget for the account with email alerts (#55 decided the amount and recipients)."""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_budgets as budgets
from constructs import Construct


class BudgetsStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        budget_name: str,
        monthly_usd: float,
        alert_emails: Sequence[str],
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        subscribers = [budgets.CfnBudget.SubscriberProperty(subscription_type="EMAIL", address=a) for a in alert_emails]

        def alert(threshold: int, notification_type: str) -> budgets.CfnBudget.NotificationWithSubscribersProperty:
            return budgets.CfnBudget.NotificationWithSubscribersProperty(
                notification=budgets.CfnBudget.NotificationProperty(
                    notification_type=notification_type,
                    comparison_operator="GREATER_THAN",
                    threshold=threshold,
                    threshold_type="PERCENTAGE",
                ),
                subscribers=subscribers,
            )

        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name=budget_name,
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(amount=monthly_usd, unit="USD"),
            ),
            notifications_with_subscribers=[alert(80, "ACTUAL"), alert(100, "FORECASTED")],
        )
```

- [ ] **Step 7: Wire `app_stacks.py`**: add `name = f"smart-tutor-{env_name}"`; pass `budget_name=f"{name}-monthly"`, `monthly_usd=app.node.get_context("smart-tutor:budget-monthly-usd")`, `alert_emails=app.node.get_context("smart-tutor:budget-alert-emails")` to `BudgetsStack`. Import `DEPLOY_ROLE_NAME` stays in `github_deploy.py` (Task 2 uses it).

- [ ] **Step 8: Run tests — PASS.** `cd infra && uv run pytest -q`

- [ ] **Step 9: Commit** — `Create the pilot VPC, ECR repositories, and budget with CDK`

---

### Task 2: EKS cluster with node group, access entries, and Pod Identity

**Files:**
- Create: `infra/smart_tutor_infra/policies/aws-load-balancer-controller-v3.5.0.json` (already vendored, unmodified from `kubernetes-sigs/aws-load-balancer-controller` `docs/install/iam_policy.json` at tag `v3.5.0`)
- Modify: `infra/smart_tutor_infra/stacks/cluster.py`, `infra/smart_tutor_infra/app_stacks.py`
- Test: `infra/tests/test_synth.py`

**Interfaces:**
- Consumes: `NetworkStack.vpc`; `DEPLOY_ROLE_NAME` from `smart_tutor_infra.stacks.github_deploy`.
- Produces: `ClusterStack(scope, id, *, vpc: ec2.IVpc, cluster_name: str, admin_principal_arns: Sequence[str], deploy_role_name: str, **kwargs)` with attributes `cluster: eks.Cluster` and `cluster_security_group_id: str` (the EKS-created cluster security group that managed nodes, and so pods, use).

- [ ] **Step 1: Write failing tests**

```python
LB_POLICY = Path(__file__).parents[1] / "smart_tutor_infra/policies/aws-load-balancer-controller-v3.5.0.json"


def test_cluster_runs_eks_1_36_with_two_small_nodes() -> None:
    t = template(make_app(), "Cluster")

    t.has_resource_properties(
        "AWS::EKS::Cluster",
        {"Name": "smart-tutor-prod", "Version": "1.36", "AccessConfig": Match.object_like(
            {"AuthenticationMode": "API", "BootstrapClusterCreatorAdminPermissions": False})},
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
        {"AssumeRolePolicyDocument": {"Statement": [Match.object_like(
            {"Action": ["sts:AssumeRole", "sts:TagSession"], "Principal": {"Service": "pods.eks.amazonaws.com"}})]}},
    )
    secrets = json.dumps(t.find_resources("AWS::IAM::ManagedPolicy"))
    assert "secret:smart-tutor/*" in secrets


def test_load_balancer_controller_policy_fits_a_managed_policy() -> None:
    document = json.loads(LB_POLICY.read_text())

    assert len(json.dumps(document, separators=(",", ":"))) <= 6144
    t = template(make_app(), "Cluster")
    policies = [p["Properties"]["PolicyDocument"] for p in t.find_resources("AWS::IAM::ManagedPolicy").values()]
    assert any(len(p["Statement"]) == len(document["Statement"]) for p in policies)
```

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement `cluster.py`**

```python
"""EKS cluster with a small managed node group, access entries, and Pod Identity for the cluster add-ons (#56).

The add-ons themselves (AWS Load Balancer Controller, External Secrets, metrics-server) are Helm releases with the
values in deploy/helm/addons/; this stack only gives them IAM roles through Pod Identity.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_eks_v2 as eks
from aws_cdk import aws_iam as iam
from constructs import Construct

# The controller's official policy, unmodified, at the chart's app version (docs/install/iam_policy.json, v3.5.0).
LB_CONTROLLER_POLICY = Path(__file__).parents[1] / "policies" / "aws-load-balancer-controller-v3.5.0.json"


class ClusterStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster_name: str,
        admin_principal_arns: Sequence[str],
        deploy_role_name: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        private = ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
        self.cluster = eks.Cluster(
            self,
            "Cluster",
            cluster_name=cluster_name,
            version=eks.KubernetesVersion.V1_36,
            vpc=vpc,
            vpc_subnets=[private],
            endpoint_access=eks.EndpointAccess.PUBLIC_AND_PRIVATE,  # kubectl from laptops and GitHub runners
            default_capacity_type=eks.DefaultCapacityType.NODEGROUP,
            default_capacity=0,
            bootstrap_cluster_creator_admin_permissions=False,  # the creator is CloudFormation's role
        )
        self.cluster_security_group_id = self.cluster.cluster_security_group_id
        self.cluster.add_nodegroup_capacity(
            "Nodes",
            nodegroup_name=f"{cluster_name}-default",
            instance_types=[ec2.InstanceType("t3.large")],
            ami_type=eks.NodegroupAmiType.AL2023_X86_64_STANDARD,
            min_size=2,
            desired_size=2,
            max_size=3,
            disk_size=30,
            subnets=private,
        )
        eks.Addon(self, "PodIdentityAgent", cluster=self.cluster, addon_name="eks-pod-identity-agent")

        cluster_admin = eks.AccessPolicy.from_access_policy_name(
            "AmazonEKSClusterAdminPolicy", access_scope_type=eks.AccessScopeType.CLUSTER
        )
        for i, arn in enumerate(admin_principal_arns):
            self.cluster.grant_access(f"AdminAccess{i}", arn, [cluster_admin])
        self.cluster.grant_access(
            "DeployRoleAccess", f"arn:aws:iam::{self.account}:role/{deploy_role_name}", [cluster_admin]
        )

        self._pod_identity(
            "LoadBalancerController",
            "kube-system",
            "aws-load-balancer-controller",
            iam.PolicyDocument.from_json(json.loads(LB_CONTROLLER_POLICY.read_text())),
        )
        self._pod_identity(
            "ExternalSecrets",
            "external-secrets",
            "external-secrets",
            iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
                        resources=[f"arn:aws:secretsmanager:{self.region}:{self.account}:secret:smart-tutor/*"],
                    )
                ]
            ),
        )
        cdk.CfnOutput(self, "ClusterName", value=self.cluster.cluster_name)

    def _pod_identity(self, name: str, namespace: str, service_account: str, document: iam.PolicyDocument) -> None:
        role = iam.Role(
            self,
            f"{name}Role",
            assumed_by=iam.SessionTagsPrincipal(iam.ServicePrincipal("pods.eks.amazonaws.com")),
            managed_policies=[iam.ManagedPolicy(self, f"{name}Policy", document=document)],
        )
        eks.CfnPodIdentityAssociation(
            self,
            f"{name}PodIdentity",
            cluster_name=self.cluster.cluster_name,
            namespace=namespace,
            service_account=service_account,
            role_arn=role.role_arn,
        )
```

If `aws_eks_v2` names differ in 2.272 (e.g. `DefaultCapacityType.NODEGROUP`), check with `uv run python -c "import aws_cdk.aws_eks_v2 as e; help(e.DefaultCapacityType)"` and adapt; the tests define the required outcome.

- [ ] **Step 4: Wire in `app_stacks.py`**

```python
cluster = ClusterStack(
    app,
    f"{prefix}-Cluster",
    env=env,
    vpc=network.vpc,
    cluster_name=name,
    admin_principal_arns=app.node.get_context("smart-tutor:eks-admin-principal-arns"),
    deploy_role_name=DEPLOY_ROLE_NAME,
)
```

- [ ] **Step 5: Run — PASS.** Also `uv run cdk synth -q` must succeed (from `infra/`, real synth catches CloudFormation-level errors such as missing assets).

- [ ] **Step 6: Commit** — `Create the EKS cluster with access entries and add-on Pod Identity`

---

### Task 3: Edge stack — internal ALB, web target group, CloudFront with a VPC origin

**Files:**
- Create: `infra/smart_tutor_infra/stacks/edge.py`
- Modify: `infra/smart_tutor_infra/app_stacks.py`, `infra/smart_tutor_infra/stacks/__init__.py` (docstring unchanged)
- Test: `infra/tests/test_synth.py`

**Interfaces:**
- Consumes: `NetworkStack.vpc`, `ClusterStack.cluster_security_group_id`.
- Produces: stack `SmartTutor-prod-Edge` with outputs `CloudFrontUrl`, `DistributionId`, `WebTargetGroupName` (= `smart-tutor-prod-web`, used by the `web` chart in Task 5); constant `WEB_PORT = 8080`.

- [ ] **Step 1: Write failing tests**

```python
def test_load_balancer_is_internal_and_has_no_internet_ingress() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::LoadBalancer", {"Name": "smart-tutor-prod", "Scheme": "internal"}
    )
    rendered = json.dumps(t.to_json())
    assert "0.0.0.0/0" not in rendered
    assert "::/0" not in rendered
    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::Listener", {"Port": 80, "Protocol": "HTTP"}
    )


def test_web_target_group_takes_pod_ips_on_8080() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::ElasticLoadBalancingV2::TargetGroup",
        {"Name": "smart-tutor-prod-web", "TargetType": "ip", "Port": 8080, "Protocol": "HTTP",
         "HealthCheckPath": "/"},
    )
    t.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress", {"FromPort": 8080, "ToPort": 8080, "IpProtocol": "tcp"}
    )
    t.has_output("WebTargetGroupName", {"Value": "smart-tutor-prod-web"})


def test_cloudfront_serves_https_through_a_vpc_origin() -> None:
    t = template(make_app(), "Edge")

    t.has_resource_properties(
        "AWS::CloudFront::VpcOrigin",
        {"VpcOriginEndpointConfig": Match.object_like(
            {"Name": "smart-tutor-prod", "HTTPPort": 80, "OriginProtocolPolicy": "http-only"})},
    )
    t.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {"DistributionConfig": Match.object_like({
            "PriceClass": "PriceClass_100",
            "DefaultCacheBehavior": Match.object_like({"ViewerProtocolPolicy": "redirect-to-https"}),
            "Origins": [Match.object_like({"VpcOriginConfig": Match.any_value()})],
        })},
    )
    t.has_output("CloudFrontUrl", {})
    t.has_output("DistributionId", {})
```

Set `test_all_stacks_synthesize_in_us_east_1` to expect 9 stacks.

- [ ] **Step 2: Run — FAIL.**

- [ ] **Step 3: Implement `edge.py`**

```python
"""The public entry point (ADR 0009): CloudFront on its default *.cloudfront.net domain reaches an internal ALB
through a VPC origin. Path routing: `/` → web now; `/api/*` and `/auth/*` arrive with their slices (#57, #58).

CDK owns the ALB, its listener, and one target group per service. In the cluster, the AWS Load Balancer Controller
only registers pod IPs into a target group, through a TargetGroupBinding that names it. So one `cdk deploy` builds the
whole path, and CloudFront never waits for a load balancer that Kubernetes would create.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from constructs import Construct

WEB_PORT = 8080


class EdgeStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        vpc: ec2.IVpc,
        cluster_security_group_id: str,
        name_prefix: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The VPC origin's ENIs live in this VPC's private subnets, so the ALB accepts HTTP only from inside the VPC.
        alb_sg = ec2.SecurityGroup(
            self,
            "LoadBalancerSecurityGroup",
            vpc=vpc,
            description="Internal ALB: HTTP from the CloudFront VPC origin inside this VPC",
            allow_all_outbound=False,
        )
        alb_sg.add_ingress_rule(ec2.Peer.ipv4(vpc.vpc_cidr_block), ec2.Port.tcp(80), "CloudFront VPC origin")
        alb_sg.add_egress_rule(
            ec2.Peer.security_group_id(cluster_security_group_id), ec2.Port.tcp(WEB_PORT), "web pods"
        )
        # Pods use the EKS cluster security group; the rule lives here to keep ClusterStack free of edge concerns.
        ec2.CfnSecurityGroupIngress(
            self,
            "WebPodsFromLoadBalancer",
            group_id=cluster_security_group_id,
            ip_protocol="tcp",
            from_port=WEB_PORT,
            to_port=WEB_PORT,
            source_security_group_id=alb_sg.security_group_id,
            description="Internal ALB to web pods",
        )

        load_balancer = elbv2.ApplicationLoadBalancer(
            self,
            "LoadBalancer",
            load_balancer_name=name_prefix,
            vpc=vpc,
            internet_facing=False,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_group=alb_sg,
        )
        web_targets = elbv2.ApplicationTargetGroup(
            self,
            "WebTargets",
            target_group_name=f"{name_prefix}-web",
            vpc=vpc,
            port=WEB_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/", healthy_http_codes="200"),
            deregistration_delay=cdk.Duration.seconds(30),
        )
        load_balancer.add_listener(
            "Http", port=80, protocol=elbv2.ApplicationProtocol.HTTP, open=False, default_target_groups=[web_targets]
        )

        # No domain means no certificate for the ALB, so the CloudFront → ALB hop is HTTP. It stays on AWS's network
        # inside the VPC origin; browsers only ever speak HTTPS to CloudFront.
        origin = origins.VpcOrigin.with_application_load_balancer(
            load_balancer,
            http_port=80,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            vpc_origin_name=name_prefix,
        )
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"{name_prefix}: web (later /api, /auth)",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.USE_ORIGIN_CACHE_CONTROL_HEADERS,  # nginx sets Cache-Control
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
        )

        cdk.CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        cdk.CfnOutput(self, "WebTargetGroupName", value=web_targets.target_group_name)
```

If `target_group_name` returns a token rather than the literal, output the literal `f"{name_prefix}-web"`.

- [ ] **Step 4: Wire in `app_stacks.py`** after the cluster: `EdgeStack(app, f"{prefix}-Edge", env=env, vpc=network.vpc, cluster_security_group_id=cluster.cluster_security_group_id, name_prefix=name)`, and append it to `stacks`.

- [ ] **Step 5: Run — PASS**, and `uv run cdk synth -q` succeeds. Update `infra/pyproject.toml` description to list "edge".

- [ ] **Step 6: Commit** — `Serve the internal ALB through CloudFront with a VPC origin`

---

### Task 4: Same-origin web build and cache headers

**Files:**
- Create: `web/src/api/absoluteUrl.ts`, `web/src/api/absoluteUrl.test.ts`
- Modify: `web/src/api/client.ts`, `web/src/auth/keycloakClient.ts`, `web/Dockerfile`, `web/nginx.conf`
- Test: `web/src/api/absoluteUrl.test.ts`, plus cases in `web/src/api/client.test.ts` and `web/src/auth/keycloakClient.test.ts`

**Interfaces:**
- Produces: `absoluteUrl(url: string, origin?: string): string`; Docker build args `VITE_API_URL`, `VITE_KEYCLOAK_URL`, `VITE_KEYCLOAK_REALM`, `VITE_KEYCLOAK_CLIENT_ID`.

- [ ] **Step 1: Write failing tests**

`web/src/api/absoluteUrl.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { absoluteUrl } from "./absoluteUrl";

describe("absoluteUrl", () => {
  it("resolves a same-origin path against the page origin", () => {
    expect(absoluteUrl("/api", "https://d111.cloudfront.net")).toBe("https://d111.cloudfront.net/api");
  });

  it("keeps an absolute URL without a trailing slash", () => {
    expect(absoluteUrl("http://localhost:10450", "https://d111.cloudfront.net")).toBe("http://localhost:10450");
  });
});
```

In `client.test.ts` add (import `apiBaseUrl`; `afterEach(() => vi.unstubAllEnvs())`):

```ts
it("calls the API on the page's origin when built with VITE_API_URL=/api", () => {
  vi.stubEnv("VITE_API_URL", "/api");
  expect(apiBaseUrl()).toBe(`${window.location.origin}/api`);
});

it("falls back to the local API when VITE_API_URL is empty", () => {
  vi.stubEnv("VITE_API_URL", "");
  expect(apiBaseUrl()).toBe("http://localhost:10450");
});
```

In `keycloakClient.test.ts` add (import `authConfig`):

```ts
it("uses Keycloak on the page's origin when built with VITE_KEYCLOAK_URL=/auth", () => {
  vi.stubEnv("VITE_KEYCLOAK_URL", "/auth");
  expect(authConfig().url).toBe(`${window.location.origin}/auth`);
  vi.unstubAllEnvs();
});
```

- [ ] **Step 2: Run — FAIL.** `cd web && npx vitest run src/api src/auth`

- [ ] **Step 3: Implement**

`web/src/api/absoluteUrl.ts`:

```ts
/** Resolves a configured URL against the page's origin, so one build can use same-origin paths such as "/api". */
export function absoluteUrl(url: string, origin: string = window.location.origin): string {
  return new URL(url, origin).href.replace(/\/$/, "");
}
```

`client.ts`: `return absoluteUrl(import.meta.env.VITE_API_URL || "http://localhost:10450");` (`||`, so an empty build arg falls back).

`keycloakClient.ts`: `url: absoluteUrl(import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:10401")`, and `||` for realm and client id. Import `absoluteUrl` from `../api/absoluteUrl`.

- [ ] **Step 4: Run — PASS**, then `npm run build`.

- [ ] **Step 5: Dockerfile build args and nginx cache headers**

`web/Dockerfile`:

```dockerfile
# Local (Compose): no build args; the app calls localhost:10450 and localhost:10401.
# Pilot (one origin behind CloudFront, ADR 0009):
#   docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t <registry>/smart-tutor/web:<sha> web
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_URL
ARG VITE_KEYCLOAK_URL
ARG VITE_KEYCLOAK_REALM
ARG VITE_KEYCLOAK_CLIENT_ID
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
```

`web/nginx.conf`:

```nginx
server {
  listen 8080;
  root /usr/share/nginx/html;

  # Hashed bundles never change; index.html must be revalidated so a deploy shows at once (CloudFront honors these).
  location /assets/ {
    add_header Cache-Control "public, max-age=31536000, immutable";
    try_files $uri =404;
  }

  location / {
    add_header Cache-Control "no-cache";
    try_files $uri /index.html;  # single-page app routing
  }
}
```

- [ ] **Step 6: Verify the image** (Docker is available):

```bash
docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t smart-tutor-web:check web
docker run -d --rm --name st-web-check --read-only --tmpfs /tmp -p 18080:8080 smart-tutor-web:check
curl -sI http://localhost:18080/ | grep -i cache-control        # no-cache
curl -sI http://localhost:18080/library | grep -i "200\|cache"  # SPA route → index.html, 200
docker exec st-web-check sh -c 'grep -l "/auth" /usr/share/nginx/html/assets/*.js'  # build args baked in
docker stop st-web-check
```

Expected: nginx starts read-only; `/` and `/library` return 200 with `no-cache`; an `/assets/*.js` file returns `immutable`.

- [ ] **Step 7: Commit** — `Build the web app for one origin with /api and /auth`

---

### Task 5: `web` Helm chart, add-on values, prod values

**Files:**
- Create: `deploy/helm/smart-tutor/charts/web/templates/_helpers.tpl`, `deployment.yaml`, `service.yaml`, `targetgroupbinding.yaml` (delete `.gitkeep`)
- Modify: `deploy/helm/smart-tutor/charts/web/values.yaml`, `deploy/helm/smart-tutor/values-prod.yaml`, `deploy/helm/addons/*.yaml`

**Interfaces:**
- Consumes: target group name `smart-tutor-prod-web` (Task 3), ECR repository `smart-tutor/web` (Task 1), Pod Identity service accounts `kube-system/aws-load-balancer-controller` and `external-secrets/external-secrets` (Task 2).
- Produces: release `smart-tutor` in namespace `smart-tutor`; Service `web` (port 80 → 8080); TargetGroupBinding `web`.

- [ ] **Step 1: `charts/web/values.yaml`**

```yaml
# The React app shell (nginx on 8080). Pods register in an ALB target group that CDK owns (EdgeStack, ADR 0009).
replicaCount: 1
image:
  repository: smart-tutor/web
  tag: ""  # defaults to global.imageTag
# ALB target group to register pods in (TargetGroupBinding). Empty renders no binding, e.g. on a local cluster.
targetGroupName: ""
resources:
  requests:
    cpu: 50m
    memory: 64Mi
  limits:
    memory: 128Mi
```

- [ ] **Step 2: templates**

`_helpers.tpl`:

```yaml
{{- define "web.labels" -}}
app.kubernetes.io/name: web
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "web.image" -}}
{{- $tag := .Values.image.tag | default .Values.global.imageTag -}}
{{- if .Values.global.imageRegistry }}{{ .Values.global.imageRegistry }}/{{ end }}{{ .Values.image.repository }}:{{ $tag }}
{{- end }}
```

`deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels:
    {{- include "web.labels" . | nindent 4 }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      {{- include "web.labels" . | nindent 6 }}
  template:
    metadata:
      labels:
        {{- include "web.labels" . | nindent 8 }}
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: web
          image: {{ include "web.image" . }}
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 20
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: [ALL]
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
          volumeMounts:
            - name: tmp
              mountPath: /tmp  # nginx-unprivileged keeps its pid and temp files here
      volumes:
        - name: tmp
          emptyDir: {}
```

`service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: web
  labels:
    {{- include "web.labels" . | nindent 4 }}
spec:
  selector:
    {{- include "web.labels" . | nindent 4 }}
  ports:
    - name: http
      port: 80
      targetPort: http
```

`targetgroupbinding.yaml`:

```yaml
{{- if .Values.targetGroupName }}
# The AWS Load Balancer Controller registers the web pods' IPs in the CDK-made target group (EdgeStack).
apiVersion: elbv2.k8s.aws/v1beta1
kind: TargetGroupBinding
metadata:
  name: web
  labels:
    {{- include "web.labels" . | nindent 4 }}
spec:
  serviceRef:
    name: web
    port: 80
  targetGroupName: {{ .Values.targetGroupName }}
  targetType: ip
{{- end }}
```

- [ ] **Step 3: `values-prod.yaml`**

```yaml
# Production overrides (us-east-1). The deploy sets global.imageRegistry and global.imageTag
# (helm upgrade --set global.imageRegistry=<RegistryUri> --set global.imageTag=<commit sha>).
# The pilot (#54) runs only the US-1 services; each is enabled by its slice.
web:
  replicaCount: 2
  targetGroupName: smart-tutor-prod-web  # SmartTutor-prod-Edge output WebTargetGroupName
keycloak:
  enabled: false  # #57
api:
  enabled: false  # #58
  replicaCount: 2
jobs:
  enabled: false  # #58 (migrate)
agent:
  enabled: false
  replicaCount: 2
mcp-server:
  enabled: false
worker:
  enabled: false
```

- [ ] **Step 4: add-on values**

`addons/aws-load-balancer-controller.yaml`:

```yaml
# AWS Load Balancer Controller, chart eks/aws-load-balancer-controller 3.5.0 (https://aws.github.io/eks-charts).
# CDK owns the ALB and its target groups (EdgeStack); the controller only registers pods via TargetGroupBinding.
# IAM comes from Pod Identity (ClusterStack). Install: docs/runbooks/pilot-deploy.md, with
#   --set vpcId=<SmartTutor-prod-Network output VpcId>
clusterName: smart-tutor-prod
region: us-east-1
serviceAccount:
  name: aws-load-balancer-controller
```

`addons/external-secrets.yaml`:

```yaml
# External Secrets Operator, chart external-secrets/external-secrets 2.11.0 (https://charts.external-secrets.io).
# Syncs AWS Secrets Manager (smart-tutor/*) into Kubernetes Secrets; IAM comes from Pod Identity (ClusterStack).
installCRDs: true
serviceAccount:
  name: external-secrets
```

`addons/metrics-server.yaml`:

```yaml
# metrics-server, chart metrics-server/metrics-server 3.14.0 (https://kubernetes-sigs.github.io/metrics-server/).
args: []
```

- [ ] **Step 5: Verify**

```bash
helm lint deploy/helm/smart-tutor
helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml
helm template smart-tutor deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml \
  --set global.imageRegistry=685394474162.dkr.ecr.us-east-1.amazonaws.com --set global.imageTag=abc123
```

Expected: both lints pass; the template renders exactly a Deployment (2 replicas, image `685394474162.dkr.ecr.us-east-1.amazonaws.com/smart-tutor/web:abc123`), a Service, and a TargetGroupBinding naming `smart-tutor-prod-web`. Without `-f values-prod.yaml`, no TargetGroupBinding.

- [ ] **Step 6: Commit** — `Run the web app on EKS behind the CDK target group`

---

### Task 6: ADR, PRD, spec, and the deploy runbook

**Files:**
- Create: `sdd/adr/0009-serve-the-pilot-from-the-cloudfront-domain.md`, `docs/runbooks/pilot-deploy.md`
- Modify: `sdd/adr/README.md` (index row), `sdd/prd.md`, `sdd/specs/2026-10-02-project-structure-design.md` (stack list line ~172), `docs/runbooks/pilot-aws-prerequisites.md`, `docs/runbooks/pilot-environment-overview.md`

- [ ] **Step 1: ADR 0009** (format in `sdd/adr/README.md`; Status accepted, Date 2026-10-05). Context: no domain for the pilot; tokens must not cross the internet unencrypted; one origin avoids CORS. Decision: serve everything from the AWS-generated `https://<id>.cloudfront.net` with path routing `/` → web, `/api/*` → api, `/auth/*` → Keycloak; CloudFront reaches an **internal** ALB through a **VPC origin**; CDK owns the ALB, listener rules, and target groups, and the LB controller only registers pods (TargetGroupBinding by name); CloudFront → ALB is HTTP inside the VPC origin, since the ALB can't get a certificate without a domain; the web image uses relative `/api` and `/auth`, so it doesn't depend on the distribution. Alternatives rejected: own domain + ACM + Route 53 (no domain yet; Appendix A item 4); internet-facing ALB with a CloudFront secret header (public attack surface, ALB HTTPS needs a domain anyway); Ingress-created ALB (CloudFront would need its ARN after a Helm install, a two-phase deploy). Consequences: moving to a custom domain later = an ACM certificate in us-east-1 + an alternate domain name on the distribution + new Keycloak redirect URIs, nothing else; the default `*.cloudfront.net` certificate fixes the minimum TLS version (TLSv1 policy) — acceptable for the pilot; a new service adds a target group, listener rule, and CloudFront behavior in `EdgeStack`.

- [ ] **Step 2: PRD** — bump the status to **v2.11**, add a `Changes from v2.10` row at the top of the change rows ("Pilot hosting: served from the AWS-generated CloudFront address with path routing (`/`, `/api/*`, `/auth/*`) through a VPC origin to an internal ALB; no custom domain, DNS, or ACM certificate for now (§9.12, Appendix A item 4; ADR 0009). No product behavior changes."), set **Last updated** to 2026-10-05. §9.12 Production: replace "ACM" with the CloudFront distribution and internal ALB, and add one sentence on the single public entry point and path routing (ADR 0009). Appendix A item 4 becomes: "~~Domain and DNS …~~ Not needed for the pilot: everything is served from the CloudFront address with path routing (ADR 0009). A custom domain later needs an ACM certificate in us-east-1 and an alternate domain name on the distribution." In "Created by CDK", replace "ACM" with "internal ALB and CloudFront distribution (VPC origin)". Add decision-log row `Q44 | Pilot address | The AWS-generated CloudFront domain with path routing; no custom domain until needed (ADR 0009).`

- [ ] **Step 3: Spec** — in the infra tree line listing `smart_tutor_infra/stacks/`, add `edge (internal ALB + CloudFront)`.

- [ ] **Step 4: Runbook `docs/runbooks/pilot-deploy.md`** — PowerShell 7, run from the repo root, admin profile. Sections:
  1. **Before you start**: #55 done (`pilot-aws-prerequisites.md`); tools (Node 22, uv, AWS CLI, kubectl, helm, Docker); the same env-var hygiene as the prerequisites script (unset `AWS_ENDPOINT_URL*` and access-key variables from `.env`, set `AWS_PROFILE`, `AWS_REGION=us-east-1`, `JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1`).
  2. **Deploy the stacks** (~25 min; EKS is most of it): `Push-Location infra; uv sync; npx aws-cdk@latest diff; npx aws-cdk@latest deploy --all --require-approval broadening; Pop-Location`. Read outputs with a helper:
     ```powershell
     function Get-Output($Stack, $Key) { aws cloudformation describe-stacks --stack-name "SmartTutor-prod-$Stack" --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text }
     $VpcId = Get-Output Network VpcId; $Registry = Get-Output Registry RegistryUri; $Url = Get-Output Edge CloudFrontUrl
     ```
  3. **Connect kubectl**: `aws eks update-kubeconfig --name smart-tutor-prod --region us-east-1`; `kubectl get nodes` shows 2 Ready.
  4. **Install the add-ons** (pinned versions):
     ```powershell
     helm repo add eks https://aws.github.io/eks-charts
     helm repo add external-secrets https://charts.external-secrets.io
     helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
     helm repo update
     helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f deploy/helm/addons/aws-load-balancer-controller.yaml --set vpcId=$VpcId --wait
     helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets --create-namespace -f deploy/helm/addons/external-secrets.yaml --wait
     helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 -n kube-system -f deploy/helm/addons/metrics-server.yaml --wait
     ```
  5. **Build and push the web image**: `$Tag = git rev-parse --short=12 HEAD`; `aws ecr get-login-password | docker login --username AWS --password-stdin $Registry`; `docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$Registry/smart-tutor/web:$Tag" web`; `docker push ...`. Note: build `linux/amd64` (nodes are x86_64; add `--platform linux/amd64` on Apple silicon).
  6. **Install the app**: `helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace -f deploy/helm/smart-tutor/values-prod.yaml --set global.imageRegistry=$Registry --set global.imageTag=$Tag --wait`.
  7. **Check**: `kubectl -n smart-tutor get pods,targetgroupbindings`; target health `aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-web --query "TargetGroups[0].TargetGroupArn" --output text)` shows 2 healthy; `curl.exe -sI $Url` → 200; `curl.exe -sI ($Url -replace '^https','http')` → 301 to HTTPS; open `$Url` in a browser → the app shell (sign-in fails until #57/#58 — expected); the ALB is not public: `aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].[Scheme,DNSName]"` → `internal`, and `Resolve-DnsName <DNSName>` gives only `10.40.x.x` addresses. Check the budget email in **Billing → Budgets → smart-tutor-prod-monthly**. Delete the old $20 budget if still there (#55 follow-up).
  8. **Update after a change**: rebuild/push with the new tag, `helm upgrade` again; `cdk deploy --all` for infra changes. (#59 automates this.)
  9. **Tear down** (keeps the #55 prerequisites, which cost nothing): `helm uninstall smart-tutor -n smart-tutor --wait` first (the controller deregisters targets and removes its finalizers), then `helm uninstall` the three add-ons, then `npx aws-cdk@latest destroy SmartTutor-prod-Edge SmartTutor-prod-Cluster SmartTutor-prod-Registry SmartTutor-prod-Budgets SmartTutor-prod-Data SmartTutor-prod-Storage SmartTutor-prod-Config SmartTutor-prod-Network` (never `--all`, which would delete the GitHub deploy role). CloudFront takes ~15 min to disable and delete; if `Network` fails because the VPC origin's ENIs are still being released, wait 10 minutes and run destroy for `SmartTutor-prod-Network` again. ECR images are deleted with the repositories. (From #57 on, RDS keeps a final snapshot — that slice adds the step.)
  10. **Costs**: ~$250–300/month idle; budget $400 with alerts.

- [ ] **Step 5: Prerequisites and overview** — `pilot-aws-prerequisites.md`: change the intro sentence "When #56 writes the deploy runbook, it absorbs this file" to point to `pilot-deploy.md` as the next step; in "Human steps in the later slices", the #56 row links `pilot-deploy.md`; "Cost control" links the teardown section. `pilot-environment-overview.md`: replace "Today only the CDK bootstrap exists; the CDK stacks in `infra/` are still empty." with the current state (#56 adds network, cluster, registry, edge, budget); in the runtime diagram, the ALB label becomes `Internal Application Load Balancer<br/>(CDK EdgeStack; pods registered by the LB controller)`; in "Who builds which piece", the #56 row lists `EdgeStack` too.

- [ ] **Step 6: Commit** — `Record the CloudFront-domain decision and write the pilot deploy runbook`

---

## Final checks

```bash
cd infra && uv run pytest && uv run cdk synth -q
helm lint deploy/helm/smart-tutor && helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml
cd web && npm ci && npm run build && npm test
```

A real `cdk deploy` is a human step (#55: admin runs the first deploy from a laptop).
