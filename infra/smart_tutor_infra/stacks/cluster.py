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
