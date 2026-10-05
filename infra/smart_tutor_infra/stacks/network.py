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
