"""On-premise Host: one EC2 VM that runs Smart Tutor with Docker Compose behind Caddy (PRD §9.12, ADR 0012, #148).

- Network: a VPC of its own with one public subnet, no NAT, and an S3 gateway endpoint. The security group admits only
  TCP 80 and 443; there is no SSH and no key pair (operators use SSM Session Manager).
- Instance: Amazon Linux 2023, IMDSv2 with a hop limit of 2 so containers get the instance profile's credentials, and an
  Elastic IP. The address is `<eip>.sslip.io` unless the context `smart-tutor:on-premise-domain` names one.
- Data: a separate encrypted gp3 volume mounted at /data (Postgres and Caddy's certificates). It is not part of the
  instance: at first boot the instance attaches it by id, waiting until a replaced instance has let go of it, so the
  data survives replacing the instance. Deleting the stack keeps a snapshot.
- Deploy: `cdk deploy` uploads `deploy/` as an asset; the SSM document `<prefix>-deploy` downloads it and runs
  `deploy/on-premise/deploy.sh <image tag>`, which renders settings and secrets into a root-only env file on the VM.
  No secret is in the template, the outputs, or the user data.

ECR is native-cloud's RegistryStack; the Host only references it.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from smart_tutor_infra.names import ModeNames
from smart_tutor_infra.stacks.registry import SERVICES

DEFAULT_INSTANCE_TYPE = "t3.large"
DATA_VOLUME_GIB = 50
ROOT_VOLUME_GIB = 30  # Docker images of six services and their layers
DATA_MOUNT = "/data"
# The Compose plugin isn't packaged for Amazon Linux 2023; the release binary is checked against its published digest.
COMPOSE_VERSION = "v5.5.1"
COMPOSE_SHA256 = "db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
# The files the VM runs: deploy/on-premise (Compose, Caddy, the deploy script) and the realm and database bootstrap it
# shares with the Helm chart.
BUNDLE_DIR = Path(__file__).parents[3] / "deploy"
# Only the instance with this tag may attach the volume with this tag.
HOST_TAG = "smart-tutor:host"


class HostStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        names: ModeNames,
        instance_type: str = DEFAULT_INSTANCE_TYPE,
        domain: str | None = None,
        services: Sequence[str] = SERVICES,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.repositories = {
            service: ecr.Repository.from_repository_name(
                self, f"{service.capitalize()}Repository", f"smart-tutor/{service}"
            )
            for service in services
        }

        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.41.0.0/16"),
            max_azs=1,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24)
            ],
            gateway_endpoints={"S3": ec2.GatewayVpcEndpointOptions(service=ec2.GatewayVpcEndpointAwsService.S3)},
        )
        subnet = vpc.public_subnets[0]

        security_group = ec2.SecurityGroup(
            self,
            "SecurityGroup",
            vpc=vpc,
            description="Smart Tutor on-premise host: HTTP and HTTPS only",
            allow_all_outbound=True,  # ECR, Let's Encrypt, Bedrock, SSM, Secrets Manager
        )
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "Let's Encrypt challenge, redirect")
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")

        volume = ec2.Volume(
            self,
            "DataVolume",
            availability_zone=subnet.availability_zone,
            size=cdk.Size.gibibytes(DATA_VOLUME_GIB),
            volume_type=ec2.EbsDeviceVolumeType.GP3,
            encrypted=True,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
            volume_name=f"{names.resource_prefix}-data",
        )
        cdk.Tags.of(volume).add(HOST_TAG, names.resource_prefix)

        bundle = s3_assets.Asset(self, "Bundle", path=str(BUNDLE_DIR), exclude=["**/__pycache__"])

        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Smart Tutor on-premise host: pull images, read its settings and secrets, managed by SSM",
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
        )
        role.add_to_policy(iam.PolicyStatement(sid="EcrLogin", actions=["ecr:GetAuthorizationToken"], resources=["*"]))
        role.add_to_policy(
            iam.PolicyStatement(
                sid="EcrPullAppImages",
                actions=["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
                resources=[repo.repository_arn for repo in self.repositories.values()],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSettings",
                actions=["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"],
                resources=[
                    self.format_arn(service="ssm", resource="parameter", resource_name=names.ssm_path.lstrip("/")),
                    self.format_arn(
                        service="ssm", resource="parameter", resource_name=f"{names.ssm_path.lstrip('/')}/*"
                    ),
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSecrets",
                actions=["secretsmanager:GetSecretValue"],
                resources=[
                    self.format_arn(
                        service="secretsmanager",
                        resource="secret",
                        resource_name=f"{names.secret_prefix}/*",
                        arn_format=cdk.ArnFormat.COLON_RESOURCE_NAME,
                    )
                ],
            )
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="AttachDataVolume",
                actions=["ec2:AttachVolume"],
                resources=[
                    self.format_arn(service="ec2", resource="volume", resource_name=volume.volume_id),
                    self.format_arn(service="ec2", resource="instance", resource_name="*"),
                ],
                conditions={"StringEquals": {f"aws:ResourceTag/{HOST_TAG}": names.resource_prefix}},
            )
        )
        bundle.grant_read(role)

        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[subnet]),
            instance_type=ec2.InstanceType(instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=security_group,
            role=role,
            user_data=_user_data(volume.volume_id, self.region),
            http_tokens=ec2.HttpTokens.REQUIRED,
            http_put_response_hop_limit=2,  # one hop for the host, one for the Docker bridge
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        ROOT_VOLUME_GIB, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True
                    ),
                )
            ],
        )
        cdk.Tags.of(instance).add(HOST_TAG, names.resource_prefix)
        cdk.Tags.of(instance).add("Name", names.resource_prefix)

        address = ec2.CfnEIP(self, "Address", domain="vpc")
        ec2.CfnEIPAssociation(
            self, "AddressAssociation", allocation_id=address.attr_allocation_id, instance_id=instance.instance_id
        )
        domain = domain or cdk.Fn.join("", [address.attr_public_ip, ".sslip.io"])

        # Database and test-learner secrets (Keycloak's are in ConfigStack). deploy.sh resets the database passwords to
        # these values on every deploy, so a restored volume or a rotated secret gets back in sync.
        for construct_name, name in (
            ("PostgresSecret", "db/postgres"),
            ("AppDatabaseSecret", "db/app"),
            ("KeycloakDatabaseSecret", "db/keycloak"),
        ):
            secretsmanager.Secret(
                self,
                construct_name,
                secret_name=f"{names.secret_prefix}/{name}",
                description=f"Password of the on-premise PostgreSQL role for {name}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    exclude_punctuation=True, password_length=32
                ),
            )
        secretsmanager.Secret(
            self,
            "TestLearnerSecret",
            secret_name=f"{names.secret_prefix}/keycloak/test-learner",
            description="The test learner deploy.sh seeds in the smart-tutor realm (smoke tests, demos)",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                # The realm uses the email as the username.
                secret_string_template='{"username": "test-learner@example.com"}',
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=24,
            ),
        )

        # Settings deploy.sh reads (the per-file limits and time zone are ConfigStack's, under the same path).
        for name, value in (
            ("domain", domain),
            ("bundle", bundle.s3_object_url),
            ("registry", f"{self.account}.dkr.ecr.{self.region}.{self.url_suffix}"),
            ("documents-bucket", names.documents_bucket(self.account)),
            ("ingest-queue-url", f"https://sqs.{self.region}.{self.url_suffix}/{self.account}/{names.ingest_queue}"),
        ):
            ssm.StringParameter(
                self, f"Host-{name}", parameter_name=f"{names.ssm_path}/host/{name}", string_value=value
            )

        document = ssm.CfnDocument(
            self,
            "DeployDocument",
            name=f"{names.data_prefix}-deploy",
            document_type="Command",
            update_method="NewVersion",  # a named document is otherwise replaced, which CloudFormation refuses
            content={
                "schemaVersion": "2.2",
                "description": "Deploy one image tag of Smart Tutor on the on-premise host"
                " (docs/runbooks/on-premise-deploy.md)",
                "parameters": {
                    "ImageTag": {
                        "type": "String",
                        "description": "Full commit SHA whose images to run",
                        "allowedPattern": "^[0-9a-f]{40}$",
                    }
                },
                "mainSteps": [
                    {
                        "action": "aws:runShellScript",
                        "name": "deploy",
                        "inputs": {
                            "timeoutSeconds": "1800",
                            "runCommand": _deploy_commands(names, self.region),
                        },
                    }
                ],
            },
        )

        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(self, "PublicIp", value=address.attr_public_ip)
        cdk.CfnOutput(self, "PublicUrl", value=f"https://{domain}")
        cdk.CfnOutput(self, "DataVolumeId", value=volume.volume_id)
        cdk.CfnOutput(self, "DeployDocumentName", value=document.ref)


def _user_data(volume_id: str, region: str) -> ec2.UserData:
    """First boot: attach and mount the data volume, then install Docker and Compose. Holds no secret."""
    user_data = ec2.UserData.for_linux()
    user_data.add_commands(
        "set -euo pipefail",
        f"volume_id={volume_id}",
        f"region={region}",
        "imds=http://169.254.169.254/latest",
        'token=$(curl -sf -X PUT "$imds/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")',
        'instance_id=$(curl -sf -H "X-aws-ec2-metadata-token: $token" "$imds/meta-data/instance-id")',
        # Nitro instances name an EBS volume by its id without the dash. A replaced instance holds the volume until
        # CloudFormation terminates it after the update, so keep asking until the attach succeeds.
        'device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${volume_id//-/}"',
        'until [ -e "$device" ]; do',
        '  aws ec2 attach-volume --region "$region" --volume-id "$volume_id" --instance-id "$instance_id"'
        " --device /dev/sdf"
        ' >/dev/null 2>&1 || echo "Waiting for $volume_id to be free"',
        "  sleep 10",
        "done",
        # Only a blank volume is formatted; without -f, mkfs.xfs also refuses to overwrite an existing file system.
        '[ -n "$(blkid -o value -s TYPE "$device")" ] || mkfs.xfs "$device"',
        f"mkdir -p {DATA_MOUNT}",
        'uuid=$(blkid -o value -s UUID "$device")',
        f'grep -q "$uuid" /etc/fstab || echo "UUID=$uuid {DATA_MOUNT} xfs defaults,nofail 0 2" >> /etc/fstab',
        f"mount {DATA_MOUNT}",
        "dnf install -y docker unzip",
        # Containers write Postgres data under /data: Docker must never start them before the volume is mounted.
        "mkdir -p /etc/systemd/system/docker.service.d",
        f"printf '[Unit]\\nRequiresMountsFor={DATA_MOUNT}\\n' > /etc/systemd/system/docker.service.d/data-volume.conf",
        "systemctl daemon-reload",
        "systemctl enable --now docker",
        "mkdir -p /usr/local/lib/docker/cli-plugins",
        "curl -sfL -o /usr/local/lib/docker/cli-plugins/docker-compose"
        f" https://github.com/docker/compose/releases/download/{COMPOSE_VERSION}/docker-compose-linux-x86_64",
        f'echo "{COMPOSE_SHA256}  /usr/local/lib/docker/cli-plugins/docker-compose" | sha256sum -c -',
        "chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose",
    )
    return user_data


def _deploy_commands(names: ModeNames, region: str) -> list[str]:
    """The SSM document's script: fetch the bundle this stack uploaded, then run deploy.sh with the tag."""
    return [
        "set -euo pipefail",
        f"export AWS_REGION={region} AWS_DEFAULT_REGION={region}",
        f"bundle=$(aws ssm get-parameter --name {names.ssm_path}/host/bundle --query Parameter.Value --output text)",
        "rm -rf /opt/smart-tutor.new /tmp/smart-tutor-bundle.zip",
        'aws s3 cp --only-show-errors "$bundle" /tmp/smart-tutor-bundle.zip',
        "unzip -q /tmp/smart-tutor-bundle.zip -d /opt/smart-tutor.new",
        "rm -rf /opt/smart-tutor /tmp/smart-tutor-bundle.zip",
        "mv /opt/smart-tutor.new /opt/smart-tutor",
        f"SMART_TUTOR_PREFIX={names.data_prefix} bash /opt/smart-tutor/on-premise/deploy.sh '{{{{ ImageTag }}}}'",
    ]
