"""The public entry point (ADR 0009): CloudFront on its default *.cloudfront.net domain reaches an internal ALB
through a VPC origin. Path routing: `/` → web, `/auth/*` → Keycloak (#57), `/api/*` → API (#58).

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

POD_PORT = 8080  # web, Keycloak, and the API all listen here, so one ALB → pod rule covers them


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
            ec2.Peer.security_group_id(cluster_security_group_id), ec2.Port.tcp(POD_PORT), "web, Keycloak, and API pods"
        )
        # Pods use the EKS cluster security group; the rule lives here to keep ClusterStack free of edge concerns.
        ec2.CfnSecurityGroupIngress(
            self,
            "WebPodsFromLoadBalancer",
            group_id=cluster_security_group_id,
            ip_protocol="tcp",
            from_port=POD_PORT,
            to_port=POD_PORT,
            source_security_group_id=alb_sg.security_group_id,
            description="Internal ALB to web, Keycloak, and API pods",
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
        web_target_group_name = f"{name_prefix}-web"  # one name for the group and the output, so they cannot drift
        web_targets = elbv2.ApplicationTargetGroup(
            self,
            "WebTargets",
            target_group_name=web_target_group_name,
            vpc=vpc,
            port=POD_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            health_check=elbv2.HealthCheck(path="/", healthy_http_codes="200"),
            deregistration_delay=cdk.Duration.seconds(30),
        )
        keycloak_target_group_name = f"{name_prefix}-keycloak"
        keycloak_targets = elbv2.ApplicationTargetGroup(
            self,
            "KeycloakTargets",
            target_group_name=keycloak_target_group_name,
            vpc=vpc,
            port=POD_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            # Healthy only once the production realm is imported, the first thing every sign-in needs.
            health_check=elbv2.HealthCheck(
                path="/auth/realms/smart-tutor/.well-known/openid-configuration", healthy_http_codes="200"
            ),
            deregistration_delay=cdk.Duration.seconds(30),
        )
        api_target_group_name = f"{name_prefix}-api"
        api_targets = elbv2.ApplicationTargetGroup(
            self,
            "ApiTargets",
            target_group_name=api_target_group_name,
            vpc=vpc,
            port=POD_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            target_type=elbv2.TargetType.IP,
            # Through the API's root path (SMART_TUTOR_ROOT_PATH=/api), as CloudFront forwards it; needs no token.
            health_check=elbv2.HealthCheck(path="/api/healthz", healthy_http_codes="200"),
            deregistration_delay=cdk.Duration.seconds(30),
        )
        listener = load_balancer.add_listener(
            "Http", port=80, protocol=elbv2.ApplicationProtocol.HTTP, open=False, default_target_groups=[web_targets]
        )
        listener.add_target_groups(
            "Keycloak",
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/auth/*"])],
            target_groups=[keycloak_targets],
        )
        listener.add_target_groups(
            "Api",
            priority=20,
            conditions=[elbv2.ListenerCondition.path_patterns(["/api/*"])],
            target_groups=[api_targets],
        )

        # No domain means no certificate for the ALB, so the CloudFront → ALB hop is HTTP. It stays on AWS's network
        # inside the VPC origin; browsers only ever speak HTTPS to CloudFront.
        origin = origins.VpcOrigin.with_application_load_balancer(
            load_balancer,
            http_port=80,
            protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
            vpc_origin_name=name_prefix,
            # The ALB sets X-Forwarded-Proto: http, so Keycloak would mark its session cookies non-Secure. CloudFront
            # overwrites any viewer-sent Forwarded header, so Keycloak can trust this one (KC_PROXY_HEADERS=forwarded).
            custom_headers={"Forwarded": "proto=https"},
        )
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            comment=f"{name_prefix}: web, /auth, /api",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
            default_behavior=cloudfront.BehaviorOptions(
                origin=origin,
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.USE_ORIGIN_CACHE_CONTROL_HEADERS,  # nginx sets Cache-Control
                response_headers_policy=cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
            ),
            additional_behaviors={
                "/auth/*": cloudfront.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,  # login form POST, admin REST PUT/DELETE
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    # AllViewer forwards the viewer's Host: Keycloak builds the backchannel URLs in its discovery
                    # document (token_endpoint, jwks_uri) from the request Host, and the ALB routes by path only.
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
                ),
                "/api/*": cloudfront.BehaviorOptions(
                    origin=origin,
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,  # learner data, per token
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,  # forwards Authorization
                ),
            },
        )

        cdk.CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "DistributionId", value=distribution.distribution_id)
        cdk.CfnOutput(self, "WebTargetGroupName", value=web_target_group_name)
        cdk.CfnOutput(self, "KeycloakTargetGroupName", value=keycloak_target_group_name)
        cdk.CfnOutput(self, "ApiTargetGroupName", value=api_target_group_name)
