"""Langfuse host: one EC2 VM that runs self-hosted Langfuse v4 with Docker Compose behind Caddy, shared by any app that
sends it traces, scores, and datasets (spec sdd/specs/2026-10-14-off-hours-and-langfuse-host-design.md §6, ADR 0021).

- Network: a VPC of its own (10.42.0.0/16) with one public subnet, no NAT, and an S3 gateway endpoint. The security
  group admits only TCP 80 and 443; no SSH and no key pair (SSM Session Manager).
- Instance: Amazon Linux 2023, IMDSv2 with a hop limit of 2 so containers get the instance role, and an Elastic IP.
  The address is the context `langfuse:domain` (a DuckDNS name) or `<eip>.sslip.io`.
- Data: a separate encrypted gp3 volume at /data (Postgres, ClickHouse, Valkey, Caddy's certificates), attached at first
  boot by id so it outlives a replaced instance, snapshotted daily (kept 7 days).
- Files: an S3 bucket for Langfuse's event and media uploads, reached with the instance role (no access keys).
- Deploy: `cdk deploy` uploads `deploy/` as an asset; the SSM document `langfuse-deploy` unpacks it to /opt/langfuse and
  runs deploy.sh, which renders settings and secrets into a root-only env file. No secret is in the template, the
  outputs, or the user data.
- Off-hours (ADR 0022): stopped at 18:00 and 00:00, started by hand (no schedule), Asia/Ho_Chi_Minh. No CloudWatch alarms; a failed
  weekly patching window emails `langfuse-alerts`.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_dlm as dlm
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_events as events
from aws_cdk import aws_events_targets as events_targets
from aws_cdk import aws_iam as iam
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_assets as s3_assets
from aws_cdk import aws_secretsmanager as secretsmanager
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as sns_subscriptions
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from langfuse_platform.off_hours import OffHours

PREFIX = "langfuse"
TIME_ZONE = "Asia/Ho_Chi_Minh"
DEFAULT_INSTANCE_TYPE = "t3.xlarge"
DATA_VOLUME_GIB = 100
ROOT_VOLUME_GIB = 30
DATA_MOUNT = "/data"
COMPOSE_VERSION = "v5.5.1"
COMPOSE_SHA256 = "db1889184726840f75c4f9c001048430d4f25b3be3cb084d3ddd762bc0aed576"
BUNDLE_DIR = Path(__file__).parents[1] / "deploy"
DEPLOY_DOCUMENT = f"{PREFIX}-deploy"
HOST_TAG = "langfuse:host"
SNAPSHOT_TAG = "langfuse:snapshots"
SNAPSHOT_TIME_UTC = "19:00"  # 02:00 in TIME_ZONE
SNAPSHOT_RETENTION_DAYS = 7
PATCH_SCHEDULE = "cron(20 7 ? * SUN *)"  # the host is started by hand, not at 07:00: it is patched only if running
ENSURE_HEALTHY = "/opt/langfuse/ensure-healthy.sh"
ENSURE_HEALTHY_COMMAND = (
    f"[ -f {ENSURE_HEALTHY} ] || {{ echo 'ensure-healthy.sh is missing: run the deploy document"
    f" (docs/runbooks/langfuse-host.md)' >&2; exit 1; }}; bash {ENSURE_HEALTHY}"
)
# Generated secrets deploy.sh reads: (construct id, name under langfuse/, length). Changing a secret's settings (name,
# length, punctuation) makes CloudFormation generate a new value. A new db/postgres breaks the existing database
# (POSTGRES_PASSWORD applies only at first init); a new encryption-seed makes encrypted data unreadable, because deploy.sh
# derives Langfuse's ENCRYPTION_KEY from it. tests/test_host_stack.py pins this tuple so a change is deliberate.
GENERATED_SECRETS = (
    ("NextAuthSecret", "nextauth-secret", 64),
    ("SaltSecret", "salt", 64),
    ("EncryptionSeedSecret", "encryption-seed", 64),
    ("PostgresSecret", "db/postgres", 32),
    ("ClickHouseSecret", "clickhouse", 32),
    ("ValkeySecret", "valkey", 32),
    ("InitProjectKeysSecret", "init-project-keys", 48),
)


class LangfuseHostStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        instance_type: str = DEFAULT_INSTANCE_TYPE,
        domain: str | None = None,
        admin_email: str,
        data_snapshot_id: str | None = None,
        alert_emails: Sequence[str] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        vpc = ec2.Vpc(
            self,
            "Vpc",
            ip_addresses=ec2.IpAddresses.cidr("10.42.0.0/16"),
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
            description="Langfuse host: HTTP and HTTPS only",
            allow_all_outbound=True,  # Docker Hub, Let's Encrypt, S3, SSM, Secrets Manager, DuckDNS
        )
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(80), "ACME HTTP-01 challenge, HTTPS redirect")
        security_group.add_ingress_rule(ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS")

        volume = ec2.Volume(
            self,
            f"DataVolumeFrom{data_snapshot_id}" if data_snapshot_id else "DataVolume",
            availability_zone=subnet.availability_zone,
            size=cdk.Size.gibibytes(DATA_VOLUME_GIB),
            snapshot_id=data_snapshot_id,
            volume_type=ec2.EbsDeviceVolumeType.GP3,
            encrypted=True,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
            volume_name=f"{PREFIX}-data",
        )
        cdk.Tags.of(volume).add(HOST_TAG, PREFIX)
        cdk.Tags.of(volume).add(SNAPSHOT_TAG, PREFIX)

        bundle = s3_assets.Asset(self, "Bundle", path=str(BUNDLE_DIR))

        role = iam.Role(
            self,
            "InstanceRole",
            assumed_by=iam.ServicePrincipal("ec2.amazonaws.com"),
            description="Langfuse host: read its settings and secrets, use its bucket, managed by SSM",
            managed_policies=[iam.ManagedPolicy.from_aws_managed_policy_name("AmazonSSMManagedInstanceCore")],
        )
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadSettings",
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[self.format_arn(service="ssm", resource="parameter", resource_name=f"{PREFIX}/host/*")],
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
                        resource_name=f"{PREFIX}/*",
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
                conditions={"StringEquals": {f"aws:ResourceTag/{HOST_TAG}": PREFIX}},
            )
        )
        # Only this bundle: the CDK assets bucket is shared with every other stack in the account and region.
        role.add_to_policy(
            iam.PolicyStatement(
                sid="ReadBundle",
                actions=["s3:GetObject"],
                resources=[bundle.bucket.arn_for_objects(bundle.s3_object_key)],
            )
        )

        instance = ec2.Instance(
            self,
            "Instance",
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnets=[subnet]),
            instance_type=ec2.InstanceType(instance_type),
            machine_image=ec2.MachineImage.latest_amazon_linux2023(),
            security_group=security_group,
            role=role,
            user_data=_user_data(volume.volume_id, self.region, data_snapshot_id),
            http_tokens=ec2.HttpTokens.REQUIRED,
            http_put_response_hop_limit=2,  # one hop for the host, one for the Docker bridge
            user_data_causes_replacement=True,
            block_devices=[
                ec2.BlockDevice(
                    device_name="/dev/xvda",
                    volume=ec2.BlockDeviceVolume.ebs(
                        ROOT_VOLUME_GIB, volume_type=ec2.EbsDeviceVolumeType.GP3, encrypted=True
                    ),
                )
            ],
        )
        cdk.Tags.of(instance).add(HOST_TAG, PREFIX)
        cdk.Tags.of(instance).add("Name", PREFIX)
        cdk.Tags.of(instance).add("PatchGroup", PREFIX)

        address = ec2.CfnEIP(self, "Address", domain="vpc")
        ec2.CfnEIPAssociation(
            self, "AddressAssociation", allocation_id=address.attr_allocation_id, instance_id=instance.instance_id
        )
        domain = domain or cdk.Fn.join("", [address.attr_public_ip, ".sslip.io"])
        origin = f"https://{domain}" if not cdk.Token.is_unresolved(domain) else "https://*.sslip.io"

        bucket = s3.Bucket(
            self,
            "Bucket",
            bucket_name=f"{PREFIX}-{self.account}-{self.region}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            # Langfuse's media uploads and views use presigned URLs from the browser.
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.PUT],
                    allowed_origins=[origin],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )
        bucket.grant_read_write(role)

        for construct_name, name, length in GENERATED_SECRETS:
            secretsmanager.Secret(
                self,
                construct_name,
                secret_name=f"{PREFIX}/{name}",
                description=f"Langfuse host: {name}",
                generate_secret_string=secretsmanager.SecretStringGenerator(
                    exclude_punctuation=True, password_length=length
                ),
            )
        secretsmanager.Secret(
            self,
            "AdminSecret",
            secret_name=f"{PREFIX}/admin",
            description="Langfuse host: the first admin, created by headless initialization",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template=json.dumps({"email": admin_email}),
                generate_string_key="password",
                exclude_punctuation=True,
                password_length=24,
                require_each_included_type=True,
            ),
        )

        for name, value in (
            ("domain", domain),
            ("bundle", bundle.s3_object_url),
            ("bucket", bucket.bucket_name),
            # Sign-up stays off; the runbook sets this to true for one deploy while an invited person signs up.
            ("allow-signup", "false"),
        ):
            ssm.StringParameter(self, f"Host-{name}", parameter_name=f"/{PREFIX}/host/{name}", string_value=value)

        document = ssm.CfnDocument(
            self,
            "DeployDocument",
            name=DEPLOY_DOCUMENT,
            document_type="Command",
            update_method="NewVersion",
            content={
                "schemaVersion": "2.2",
                "description": "Deploy Langfuse on the Langfuse host (docs/runbooks/langfuse-host.md)",
                "mainSteps": [
                    {
                        "action": "aws:runShellScript",
                        "name": "deploy",
                        "inputs": {"timeoutSeconds": "1800", "runCommand": _deploy_commands(self.region)},
                    }
                ],
            },
        )

        topic = sns.Topic(self, "Alerts", topic_name=f"{PREFIX}-alerts")
        for email in alert_emails:
            topic.add_subscription(sns_subscriptions.EmailSubscription(email))
        self._snapshots()
        _patching(self, instance, topic)
        OffHours(self, "OffHours", instance=instance, name_prefix=PREFIX, time_zone=TIME_ZONE)

        cdk.CfnOutput(self, "InstanceId", value=instance.instance_id)
        cdk.CfnOutput(self, "PublicIp", value=address.attr_public_ip)
        cdk.CfnOutput(self, "PublicUrl", value=f"https://{domain}")
        cdk.CfnOutput(self, "DataVolumeId", value=volume.volume_id)
        cdk.CfnOutput(self, "BucketName", value=bucket.bucket_name)
        cdk.CfnOutput(self, "DeployDocumentName", value=document.ref)

    def _snapshots(self) -> None:
        role = iam.Role(
            self,
            "SnapshotRole",
            assumed_by=iam.ServicePrincipal("dlm.amazonaws.com"),
            description="Data Lifecycle Manager: snapshot the Langfuse data volume",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSDataLifecycleManagerServiceRole")
            ],
        )
        dlm.CfnLifecyclePolicy(
            self,
            "DataVolumeSnapshots",
            description=f"{PREFIX} data volume daily kept {SNAPSHOT_RETENTION_DAYS} days",
            state="ENABLED",
            execution_role_arn=role.role_arn,
            policy_details=dlm.CfnLifecyclePolicy.PolicyDetailsProperty(
                policy_type="EBS_SNAPSHOT_MANAGEMENT",
                resource_types=["VOLUME"],
                target_tags=[cdk.CfnTag(key=SNAPSHOT_TAG, value=PREFIX)],
                schedules=[
                    dlm.CfnLifecyclePolicy.ScheduleProperty(
                        name="daily",
                        copy_tags=True,
                        create_rule=dlm.CfnLifecyclePolicy.CreateRuleProperty(
                            interval=24, interval_unit="HOURS", times=[SNAPSHOT_TIME_UTC]
                        ),
                        retain_rule=dlm.CfnLifecyclePolicy.RetainRuleProperty(
                            interval=SNAPSHOT_RETENTION_DAYS, interval_unit="DAYS"
                        ),
                    )
                ],
            ),
        )


def _user_data(volume_id: str, region: str, data_snapshot_id: str | None) -> ec2.UserData:
    """First boot: attach and mount the data volume, then install Docker and Compose. Holds no secret."""
    user_data = ec2.UserData.for_linux()
    user_data.add_commands(
        f"# Data volume from snapshot: {data_snapshot_id or 'none'}",
        "set -euo pipefail",
        f"volume_id={volume_id}",
        f"region={region}",
        "imds=http://169.254.169.254/latest",
        'token=$(curl -sf -X PUT "$imds/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 300")',
        'instance_id=$(curl -sf -H "X-aws-ec2-metadata-token: $token" "$imds/meta-data/instance-id")',
        'device="/dev/disk/by-id/nvme-Amazon_Elastic_Block_Store_${volume_id//-/}"',
        'until [ -e "$device" ]; do',
        '  aws ec2 attach-volume --region "$region" --volume-id "$volume_id" --instance-id "$instance_id"'
        " --device /dev/sdf"
        ' >/dev/null 2>&1 || echo "Waiting for $volume_id to be free"',
        "  sleep 10",
        "done",
        '[ -n "$(blkid -o value -s TYPE "$device")" ] || mkfs.xfs "$device"',
        f"mkdir -p {DATA_MOUNT}",
        'uuid=$(blkid -o value -s UUID "$device")',
        f'grep -q "$uuid" /etc/fstab || echo "UUID=$uuid {DATA_MOUNT} xfs defaults,nofail 0 2" >> /etc/fstab',
        f"mount {DATA_MOUNT}",
        "dnf install -y docker unzip",
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


def _deploy_commands(region: str) -> list[str]:
    """The SSM document's script: wait for first boot, fetch the bundle `cdk deploy` uploaded, run deploy.sh."""
    return [
        "set -euo pipefail",
        "cloud-init status --wait > /dev/null || echo 'Warning: first boot (cloud-init) reported an error; see /var/log/cloud-init-output.log' >&2",
        f"export AWS_REGION={region} AWS_DEFAULT_REGION={region}",
        f"bundle=$(aws ssm get-parameter --name /{PREFIX}/host/bundle --query Parameter.Value --output text)",
        "rm -rf /opt/langfuse.new /tmp/langfuse-bundle.zip",
        'aws s3 cp --only-show-errors "$bundle" /tmp/langfuse-bundle.zip',
        "unzip -q /tmp/langfuse-bundle.zip -d /opt/langfuse.new",
        "rm -rf /opt/langfuse /tmp/langfuse-bundle.zip",
        "mv /opt/langfuse.new /opt/langfuse",
        "bash /opt/langfuse/deploy.sh",
    ]


def _patching(scope: Construct, instance: ec2.Instance, topic: sns.ITopic) -> None:
    """Weekly security patching through SSM Patch Manager, then a check that every service is healthy again."""
    ssm.CfnPatchBaseline(
        scope,
        "PatchBaseline",
        name=f"{PREFIX}-security",
        description="Security updates for the Langfuse host",
        operating_system="AMAZON_LINUX_2023",
        patch_groups=[PREFIX],
        approval_rules=ssm.CfnPatchBaseline.RuleGroupProperty(
            patch_rules=[
                ssm.CfnPatchBaseline.RuleProperty(
                    approve_after_days=0,
                    compliance_level="HIGH",
                    patch_filter_group=ssm.CfnPatchBaseline.PatchFilterGroupProperty(
                        patch_filters=[
                            ssm.CfnPatchBaseline.PatchFilterProperty(key="CLASSIFICATION", values=["Security"])
                        ]
                    ),
                )
            ]
        ),
    )
    window = ssm.CfnMaintenanceWindow(
        scope,
        "PatchWindow",
        name=f"{PREFIX}-patching",
        description="Weekly security patching of the Langfuse host (docs/runbooks/langfuse-host.md)",
        schedule=PATCH_SCHEDULE,
        schedule_timezone=TIME_ZONE,
        duration=3,
        cutoff=1,
        allow_unassociated_targets=False,
    )
    target = ssm.CfnMaintenanceWindowTarget(
        scope,
        "PatchWindowTarget",
        window_id=window.ref,
        resource_type="INSTANCE",
        targets=[ssm.CfnMaintenanceWindowTarget.TargetsProperty(key="InstanceIds", values=[instance.instance_id])],
    )

    def task(construct_id: str, priority: int, document: str, parameters: dict[str, list[str]]) -> None:
        ssm.CfnMaintenanceWindowTask(
            scope,
            construct_id,
            window_id=window.ref,
            priority=priority,
            task_type="RUN_COMMAND",
            task_arn=document,
            targets=[ssm.CfnMaintenanceWindowTask.TargetProperty(key="WindowTargetIds", values=[target.ref])],
            max_concurrency="1",
            max_errors="1",
            cutoff_behavior="CONTINUE_TASK",
            task_invocation_parameters=ssm.CfnMaintenanceWindowTask.TaskInvocationParametersProperty(
                maintenance_window_run_command_parameters=ssm.CfnMaintenanceWindowTask.MaintenanceWindowRunCommandParametersProperty(
                    parameters=parameters
                )
            ),
        )

    task("PatchTask", 1, "AWS-RunPatchBaseline", {"Operation": ["Install"], "RebootOption": ["RebootIfNeeded"]})
    task("HealthTask", 2, "AWS-RunShellScript", {"commands": [ENSURE_HEALTHY_COMMAND], "executionTimeout": ["1200"]})

    events.Rule(
        scope,
        "PatchWindowFailedRule",
        description="Email when the Langfuse patching window fails or times out",
        event_pattern=events.EventPattern(
            source=["aws.ssm"],
            detail_type=["Maintenance Window Execution State-change Notification"],
            detail={"window-id": [window.ref], "status": ["FAILED", "TIMED_OUT"]},
        ),
        targets=[
            events_targets.SnsTopic(
                topic,
                message=events.RuleTargetInput.from_text(
                    f"The patching window {PREFIX}-patching ended {events.EventField.from_path('$.detail.status')}"
                    f" (execution {events.EventField.from_path('$.detail.window-execution-id')})."
                    " See docs/runbooks/langfuse-host.md."
                ),
            )
        ],
    )
