"""The on-premise Host stack and the files it runs on the VM (#148, PRD §9.12, ADR 0012)."""

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from aws_cdk.assertions import Match, Template

from smart_tutor_infra.names import ON_PREMISE
from smart_tutor_infra.stacks.host import COMPOSE_SHA256, COMPOSE_VERSION
from tests.test_synth import make_app, template

ON_PREMISE_DIR = Path(__file__).parents[2] / "deploy/on-premise"


def host(**context: Any) -> Template:
    return template(make_app(**{"smart-tutor:mode": ON_PREMISE, **context}), "Host")


@pytest.fixture(scope="module")
def t() -> Template:
    return host()


def _user_data(t: Template) -> str:
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    return json.dumps(instance["Properties"]["UserData"])


def _statements(t: Template) -> dict[str, dict[str, Any]]:
    """The named statements by Sid; guards over every statement use `_all_statements`."""
    return {s["Sid"]: s for s in _all_statements(t) if "Sid" in s}


# --- network -------------------------------------------------------------------------------------------------------


def test_own_vpc_has_one_public_subnet_no_nat_and_an_s3_gateway_endpoint(t: Template) -> None:
    t.resource_count_is("AWS::EC2::VPC", 1)
    t.resource_count_is("AWS::EC2::Subnet", 1)
    t.resource_count_is("AWS::EC2::NatGateway", 0)
    t.resource_count_is("AWS::EC2::InternetGateway", 1)
    t.has_resource_properties(
        "AWS::EC2::VPCEndpoint",
        {"VpcEndpointType": "Gateway", "ServiceName": Match.object_like({"Fn::Join": Match.any_value()})},
    )
    (endpoint,) = t.find_resources("AWS::EC2::VPCEndpoint").values()
    assert ".s3" in json.dumps(endpoint["Properties"]["ServiceName"])


def test_only_http_and_https_reach_the_host(t: Template) -> None:
    (group,) = t.find_resources("AWS::EC2::SecurityGroup").values()
    ingress = group["Properties"]["SecurityGroupIngress"]
    assert sorted((r["IpProtocol"], r["FromPort"], r["ToPort"], r["CidrIp"]) for r in ingress) == [
        ("tcp", 80, 80, "0.0.0.0/0"),
        ("tcp", 443, 443, "0.0.0.0/0"),
    ]
    t.resource_count_is("AWS::EC2::SecurityGroupIngress", 0)


def test_no_ssh_key_and_imdsv2_reachable_from_containers(t: Template) -> None:
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    assert "KeyName" not in instance["Properties"]
    assert instance["Properties"]["MetadataOptions"] == {
        "HttpTokens": "required",
        "HttpPutResponseHopLimit": 2,  # the Docker bridge is a second hop
    }


def test_elastic_ip_is_associated_with_the_instance(t: Template) -> None:
    t.resource_count_is("AWS::EC2::EIP", 1)
    (instance_id,) = t.find_resources("AWS::EC2::Instance")
    t.has_resource_properties("AWS::EC2::EIPAssociation", {"InstanceId": {"Ref": instance_id}})


# --- instance and data volume --------------------------------------------------------------------------------------


def test_instance_is_a_t3_large_amazon_linux_2023_with_an_encrypted_root(t: Template) -> None:
    t.has_resource_properties(
        "AWS::EC2::Instance",
        {
            "InstanceType": "t3.large",
            "BlockDeviceMappings": [
                {"DeviceName": "/dev/xvda", "Ebs": Match.object_like({"Encrypted": True, "VolumeType": "gp3"})}
            ],
        },
    )
    image_parameters = [p for p in t.to_json()["Parameters"] if "al2023" in p.lower()]
    assert image_parameters, "the AMI should come from the Amazon Linux 2023 SSM parameter"


def test_instance_size_is_one_setting() -> None:
    host(**{"smart-tutor:on-premise-instance-type": "t3.xlarge"}).has_resource_properties(
        "AWS::EC2::Instance", {"InstanceType": "t3.xlarge"}
    )


def test_data_volume_is_separate_encrypted_gp3_and_kept_as_a_snapshot(t: Template) -> None:
    t.has_resource(
        "AWS::EC2::Volume",
        {
            "DeletionPolicy": "Snapshot",
            "UpdateReplacePolicy": "Snapshot",
            "Properties": Match.object_like({"Size": 50, "VolumeType": "gp3", "Encrypted": True}),
        },
    )
    # Not in the instance's block devices: replacing the instance leaves it alone.
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    assert len(instance["Properties"]["BlockDeviceMappings"]) == 1
    t.resource_count_is("AWS::EC2::VolumeAttachment", 0)


def test_data_volume_is_in_the_instance_subnet_zone(t: Template) -> None:
    (volume,) = t.find_resources("AWS::EC2::Volume").values()
    (subnet,) = t.find_resources("AWS::EC2::Subnet").values()
    assert volume["Properties"]["AvailabilityZone"] == subnet["Properties"]["AvailabilityZone"]


def test_user_data_attaches_and_mounts_the_volume_before_docker_and_holds_no_secret(t: Template) -> None:
    user_data = _user_data(t)
    (volume_id,) = t.find_resources("AWS::EC2::Volume")

    assert "aws ec2 attach-volume" in user_data and volume_id in user_data
    assert "RequiresMountsFor=/data" in user_data
    assert user_data.index("mount /data") < user_data.index("systemctl enable --now docker")
    assert f"compose/releases/download/{COMPOSE_VERSION}/" in user_data
    assert f"{COMPOSE_SHA256}  /usr/local/lib/docker/cli-plugins/docker-compose" in user_data
    assert not re.search(r"secretsmanager|password|resolve:secrets", user_data, re.IGNORECASE)


def test_only_the_tagged_host_may_attach_the_tagged_volume(t: Template) -> None:
    statement = _statements(t)["AttachDataVolume"]
    assert statement["Action"] == "ec2:AttachVolume"
    assert statement["Condition"] == {
        "StringEquals": {"aws:ResourceTag/smart-tutor:host": "smart-tutor-on-premise-prod"}
    }
    for kind in ("AWS::EC2::Volume", "AWS::EC2::Instance"):
        (resource,) = t.find_resources(kind).values()
        assert {"Key": "smart-tutor:host", "Value": "smart-tutor-on-premise-prod"} in resource["Properties"]["Tags"]


# --- permissions ---------------------------------------------------------------------------------------------------


def test_instance_role_pulls_images_reads_its_own_settings_and_secrets_and_is_managed_by_ssm(t: Template) -> None:
    (role,) = (
        r
        for r in t.find_resources("AWS::IAM::Role").values()
        if "ec2.amazonaws.com" in json.dumps(r["Properties"]["AssumeRolePolicyDocument"])
    )
    assert "AmazonSSMManagedInstanceCore" in json.dumps(role["Properties"]["ManagedPolicyArns"])
    statements = _statements(t)

    assert statements["EcrLogin"]["Resource"] == "*"
    pull = json.dumps(statements["EcrPullAppImages"]["Resource"])
    assert all(
        f"repository/smart-tutor-on-premise/{s}" in pull for s in ("api", "web", "keycloak", "agent", "mcp", "worker")
    )
    assert "repository/smart-tutor/" not in pull  # never native-cloud's registry (#206)
    assert "ecr:PutImage" not in json.dumps(_all_statements(t))
    assert "parameter/smart-tutor-on-premise/*" in json.dumps(statements["ReadSettings"]["Resource"])
    assert "secret:smart-tutor-on-premise/*" in json.dumps(statements["ReadSecrets"]["Resource"])
    # Nothing of native-cloud's.
    every = _all_statements(t)
    assert "parameter/smart-tutor/" not in json.dumps(every)
    assert "secret:smart-tutor/" not in json.dumps(every)
    # Only the ECR login and metrics, which have no resource, may use "*".
    assert sorted(s.get("Sid", "<unnamed>") for s in every if s["Resource"] == "*") == ["EcrLogin", "PublishJobMetrics"]


def test_instance_role_writes_the_on_premise_bucket_only_where_a_service_or_the_backup_does(t: Template) -> None:
    statements = _statements(t)
    writes = sorted(
        (action, resource)
        for action, resource in _grants(t)
        if action.startswith("s3:") and not action.startswith(("s3:Get", "s3:List"))
    )
    assert all(ON_PREMISE_BUCKET in resource for _, resource in writes)
    assert [(action, resource.rsplit("/", 1)[0].rsplit('"', 1)[1]) for action, resource in writes] == [
        ("s3:AbortMultipartUpload", "/backups"),
        ("s3:DeleteObject", "/uploads"),
        ("s3:DeleteObjectVersion", "/contents"),
        ("s3:PutObject", "/backups"),
        ("s3:PutObject", "/contents"),
        ("s3:PutObject", "/uploads"),
    ]
    assert sorted(_actions(statements["WriteDatabaseBackups"])) == ["s3:AbortMultipartUpload", "s3:PutObject"]
    resource = json.dumps(statements["WriteDatabaseBackups"]["Resource"])
    assert ON_PREMISE_BUCKET in resource and resource.endswith('/backups/*"]]}')
    # Restore reads the dumps back; listing is limited to the prefix too.
    assert json.dumps(statements["ReadDatabaseBackups"]["Resource"]).endswith('/backups/*"]]}')
    assert statements["ListDatabaseBackups"]["Condition"] == {"StringLike": {"s3:prefix": ["backups/*"]}}


def test_instance_role_publishes_metrics_only_to_its_own_namespace(t: Template) -> None:
    statement = _statements(t)["PublishJobMetrics"]
    assert statement["Action"] == "cloudwatch:PutMetricData"
    assert statement["Condition"] == {"StringEquals": {"cloudwatch:namespace": "SmartTutor/OnPremise"}}


def _actions(statement: dict[str, Any]) -> list[str]:
    actions = statement["Action"]
    return [actions] if isinstance(actions, str) else actions


def _all_statements(t: Template) -> list[dict[str, Any]]:
    return [
        s for p in t.find_resources("AWS::IAM::Policy").values() for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]


def _grants(t: Template) -> list[tuple[str, str]]:
    """Every (action, resource) pair the instance role allows; a resource is its JSON text."""
    pairs: list[tuple[str, str]] = []
    for statement in _all_statements(t):
        resources = statement["Resource"]
        for resource in resources if isinstance(resources, list) else [resources]:
            pairs.extend((action, json.dumps(resource)) for action in _actions(statement))
    return pairs


def _granted(t: Template, action: str, *fragments: str) -> bool:
    return any(a == action and all(f in r for f in fragments) for a, r in _grants(t))


ON_PREMISE_BUCKET = "smart-tutor-on-premise-documents-"


def test_instance_role_has_the_api_and_worker_bucket_permissions(t: Template) -> None:
    # One role runs every service (#149), so it holds what native-cloud gives the API and the worker separately.
    for action, prefix in (
        ("s3:PutObject", "/uploads/*"),  # the browser's presigned POST
        ("s3:PutObject", "/contents/*"),
        ("s3:GetObject", "/uploads/*"),
        ("s3:GetObject", "/contents/*"),  # also the document viewer's presigned GET (#123)
        ("s3:DeleteObject", "/uploads/*"),
        ("s3:DeleteObjectVersion", "/contents/*"),
    ):
        assert _granted(t, action, ON_PREMISE_BUCKET, f'{prefix}"'), (action, prefix)
    (list_versions,) = (s for s in _all_statements(t) if "s3:ListBucketVersions" in _actions(s))
    assert ON_PREMISE_BUCKET in json.dumps(list_versions["Resource"])
    assert list_versions["Condition"] == {"StringLike": {"s3:prefix": ["contents/*"]}}


def test_instance_role_sends_and_consumes_the_on_premise_ingest_queue(t: Template) -> None:
    for action in (
        "sqs:SendMessage",
        "sqs:ReceiveMessage",
        "sqs:DeleteMessage",
        "sqs:ChangeMessageVisibility",
        "sqs:GetQueueAttributes",
    ):
        assert _granted(t, action, "arn:aws:sqs:us-east-1:", ':smart-tutor-on-premise-ingest"'), action


def test_instance_role_invokes_the_agent_and_embedding_models(t: Template) -> None:
    for action in ("bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"):
        assert _granted(t, action, ":inference-profile/us.amazon.nova-2-lite-v1:0")
        for region in ("us-east-1", "us-east-2", "us-west-2"):
            assert _granted(t, action, f"arn:aws:bedrock:{region}::foundation-model/amazon.nova-2-lite-v1:0")
        assert _granted(
            t, action, "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-multimodal-embeddings-v1:0"
        )


def test_instance_role_names_no_native_cloud_resource(t: Template) -> None:
    rendered = json.dumps(_all_statements(t))
    assert "smart-tutor-documents-" not in rendered
    assert ":smart-tutor-ingest" not in rendered


# --- backups -------------------------------------------------------------------------------------------------------


def test_data_volume_is_snapshotted_daily_and_snapshots_are_kept_7_days(t: Template) -> None:
    (policy,) = t.find_resources("AWS::DLM::LifecyclePolicy").values()
    props = policy["Properties"]
    assert props["State"] == "ENABLED"
    assert re.fullmatch(r"[0-9A-Za-z _-]{0,500}", props["Description"])  # DLM rejects anything else at deploy time
    details = props["PolicyDetails"]
    assert details["ResourceTypes"] == ["VOLUME"]
    assert details["TargetTags"] == [{"Key": "smart-tutor:snapshots", "Value": "smart-tutor-on-premise-prod"}]
    (schedule,) = details["Schedules"]
    assert schedule["CreateRule"] == {"Interval": 24, "IntervalUnit": "HOURS", "Times": ["19:00"]}  # 02:00 ICT
    assert schedule["RetainRule"] == {"Interval": 7, "IntervalUnit": "DAYS"}
    assert schedule["CopyTags"] is True
    (role_id,) = (
        rid
        for rid, r in t.find_resources("AWS::IAM::Role").items()
        if "dlm.amazonaws.com" in json.dumps(r["Properties"]["AssumeRolePolicyDocument"])
    )
    assert props["ExecutionRoleArn"] == {"Fn::GetAtt": [role_id, "Arn"]}


def test_only_the_data_volume_carries_the_snapshot_tag(t: Template) -> None:
    tagged = [
        kind
        for kind in ("AWS::EC2::Volume", "AWS::EC2::Instance")
        for r in t.find_resources(kind).values()
        if any(tag["Key"] == "smart-tutor:snapshots" for tag in r["Properties"].get("Tags", []))
    ]
    assert tagged == ["AWS::EC2::Volume"]
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    assert not instance["Properties"].get("PropagateTagsToVolumeOnCreation")


def test_data_volume_can_be_restored_from_a_snapshot() -> None:
    restored = host(**{"smart-tutor:on-premise-data-snapshot-id": "snap-0123456789abcdef0"})
    (volume,) = restored.find_resources("AWS::EC2::Volume").values()
    assert volume["Properties"]["SnapshotId"] == "snap-0123456789abcdef0"
    (blank_volume,) = host(**{"smart-tutor:on-premise-data-snapshot-id": ""}).find_resources("AWS::EC2::Volume").values()
    assert "SnapshotId" not in blank_volume["Properties"]


def test_a_restored_data_volume_is_a_new_resource() -> None:
    # CloudFormation updates SnapshotId in place, which EC2 refuses (the restore drill, #155), so each snapshot id gets
    # its own logical id: CloudFormation creates that volume and deletes the old one after its final snapshot.
    def volume_id(snapshot_id: str) -> str:
        (logical_id,) = host(**{"smart-tutor:on-premise-data-snapshot-id": snapshot_id}).find_resources(
            "AWS::EC2::Volume"
        )
        return logical_id

    blank = volume_id("")
    assert blank == "DataVolume175940C2"  # the volume deployed before #155 stays
    first, second = volume_id("snap-0123456789abcdef0"), volume_id("snap-0fedcba9876543210")
    assert len({blank, first, second}) == 3


def test_a_new_data_volume_replaces_the_instance_so_it_attaches_at_first_boot() -> None:
    # The user data names the volume and runs only at first boot, so a changed user data must replace the instance.
    (before,) = host(**{"smart-tutor:on-premise-data-snapshot-id": ""}).find_resources("AWS::EC2::Instance")
    (after,) = host(**{"smart-tutor:on-premise-data-snapshot-id": "snap-0123456789abcdef0"}).find_resources(
        "AWS::EC2::Instance"
    )
    assert before != after


def _alarm(t: Template, metric: str) -> dict[str, Any]:
    (alarm,) = (
        a["Properties"]
        for a in t.find_resources("AWS::CloudWatch::Alarm").values()
        if a["Properties"].get("MetricName") == metric
    )
    alarm_properties: dict[str, Any] = alarm
    return alarm_properties


def test_a_failed_database_backup_raises_an_alarm_that_emails_the_alert_addresses(t: Template) -> None:
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    t.has_resource_properties(
        "AWS::SNS::Subscription",
        {"Protocol": "email", "Endpoint": "dtrungthao@gmail.com", "TopicArn": {"Ref": topic_id}},
    )
    alarm = _alarm(t, "JobFailed")
    assert alarm["Namespace"] == "SmartTutor/OnPremise"
    assert alarm["Dimensions"] == [{"Name": "Job", "Value": "smart-tutor-backup"}]
    assert alarm["Statistic"] == "Sum" and alarm["Threshold"] == 1
    assert alarm["ComparisonOperator"] == "GreaterThanOrEqualToThreshold"
    assert alarm["TreatMissingData"] == "notBreaching"
    assert alarm["AlarmActions"] == [{"Ref": topic_id}]


def test_a_failed_snapshot_raises_an_alarm(t: Template) -> None:
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    (policy_id,) = t.find_resources("AWS::DLM::LifecyclePolicy")
    alarm = _alarm(t, "SnapshotsCreateFailed")
    assert alarm["Namespace"] == "AWS/EBS"
    assert alarm["Dimensions"] == [{"Name": "DLMPolicyId", "Value": {"Ref": policy_id}}]
    assert alarm["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and alarm["Threshold"] == 1
    assert alarm["AlarmActions"] == [{"Ref": topic_id}]


# --- settings, secrets, deploy document ----------------------------------------------------------------------------


def _parameter(t: Template, name: str) -> Any:
    (value,) = (
        p["Properties"]["Value"]
        for p in t.find_resources("AWS::SSM::Parameter").values()
        if p["Properties"]["Name"] == f"/smart-tutor-on-premise/host/{name}"
    )
    return value


def test_domain_is_the_duckdns_name(t: Template) -> None:
    assert _parameter(t, "domain") == "smart-tutor.duckdns.org"


def test_an_empty_domain_falls_back_to_the_elastic_ip_on_sslip_io() -> None:
    t = host(**{"smart-tutor:on-premise-domain": ""})
    (eip_id,) = t.find_resources("AWS::EC2::EIP")
    assert _parameter(t, "domain") == {"Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]}


def test_deploy_settings_name_on_premise_resources(t: Template) -> None:
    assert "smart-tutor-on-premise-documents-" in json.dumps(_parameter(t, "documents-bucket"))
    assert "/smart-tutor-on-premise-ingest" in json.dumps(_parameter(t, "ingest-queue-url"))
    assert ".dkr.ecr." in json.dumps(_parameter(t, "registry"))
    assert _parameter(t, "repository-prefix") == "smart-tutor-on-premise"
    assert "s3://" in json.dumps(_parameter(t, "bundle"))


def test_database_test_learner_and_phoenix_secrets_are_generated(t: Template) -> None:
    secrets = {
        s["Properties"]["Name"]: s["Properties"] for s in t.find_resources("AWS::SecretsManager::Secret").values()
    }
    assert set(secrets) == {
        "smart-tutor-on-premise/db/postgres",
        "smart-tutor-on-premise/db/app",
        "smart-tutor-on-premise/db/keycloak",
        "smart-tutor-on-premise/db/phoenix",
        "smart-tutor-on-premise/keycloak/test-learner",
        "smart-tutor-on-premise/phoenix/secret",
        "smart-tutor-on-premise/phoenix/admin-password",
    }
    assert all("SecretString" not in s and s["GenerateSecretString"]["ExcludePunctuation"] for s in secrets.values())
    learner = secrets["smart-tutor-on-premise/keycloak/test-learner"]["GenerateSecretString"]
    assert learner["GenerateStringKey"] == "password"
    assert json.loads(learner["SecretStringTemplate"])["username"] == "test-learner@example.com"
    # Phoenix refuses a PHOENIX_SECRET shorter than 32 characters or without a digit and a lowercase letter.
    phoenix_secret = secrets["smart-tutor-on-premise/phoenix/secret"]["GenerateSecretString"]
    assert phoenix_secret["PasswordLength"] >= 32 and phoenix_secret["RequireEachIncludedType"] is True
    admin = secrets["smart-tutor-on-premise/phoenix/admin-password"]["GenerateSecretString"]
    assert admin["PasswordLength"] >= 12 and admin["RequireEachIncludedType"] is True


def test_deploy_document_takes_only_a_commit_sha_and_runs_the_bundled_script(t: Template) -> None:
    (document,) = t.find_resources("AWS::SSM::Document").values()
    props = document["Properties"]
    assert props["Name"] == "smart-tutor-on-premise-deploy"
    assert props["DocumentType"] == "Command"
    assert props["UpdateMethod"] == "NewVersion"
    assert props["Content"]["parameters"]["ImageTag"]["allowedPattern"] == "^[0-9a-f]{40}$"
    script = json.dumps(props["Content"]["mainSteps"][0]["inputs"]["runCommand"])
    assert "/smart-tutor-on-premise/host/bundle" in script
    assert "SMART_TUTOR_PREFIX=smart-tutor-on-premise bash /opt/smart-tutor/on-premise/deploy.sh '{{ ImageTag }}'" in (
        script
    )


def test_deploy_document_waits_for_first_boot_before_using_unzip(t: Template) -> None:
    (document,) = t.find_resources("AWS::SSM::Document").values()
    commands = document["Properties"]["Content"]["mainSteps"][0]["inputs"]["runCommand"]
    text = [json.dumps(c) for c in commands]
    wait = next(i for i, c in enumerate(text) if "cloud-init status --wait" in c)
    download = next(i for i, c in enumerate(text) if "aws s3 cp" in c)
    unzip = next(i for i, c in enumerate(text) if "unzip" in c)
    assert wait < download < unzip


def test_no_secret_reaches_the_outputs_or_the_template(t: Template) -> None:
    rendered = json.dumps(t.to_json())
    assert "resolve:secretsmanager" not in rendered
    assert '"SecretString"' not in rendered  # every secret value is generated by Secrets Manager
    outputs = t.to_json()["Outputs"]
    # Besides CDK's export of the Elastic IP, which StorageStack's CORS imports.
    assert {o for o in outputs if not o.startswith("ExportsOutput")} == {
        "InstanceId",
        "PublicIp",
        "PublicUrl",
        "DataVolumeId",
        "DeployDocumentName",
    }
    assert "Secret" not in json.dumps(outputs)


# --- files on the VM -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load((ON_PREMISE_DIR / "compose.yaml").read_text(encoding="utf-8"))


LONG_RUNNING = {"postgres", "keycloak", "api", "web", "caddy", "agent", "mcp", "worker", "egress-proxy", "phoenix"}


def test_compose_runs_the_production_services_and_no_local_emulators(compose: dict[str, Any]) -> None:
    assert set(compose["services"]) == LONG_RUNNING | {"migrate", "pg-dump"}
    assert compose["services"]["migrate"]["profiles"] == ["tools"]  # run by deploy.sh, never by `up`
    assert compose["services"]["pg-dump"]["profiles"] == ["jobs"]  # run by a systemd timer, never by `up`


def test_every_service_has_a_health_check_restart_policy_and_log_rotation(compose: dict[str, Any]) -> None:
    for name in LONG_RUNNING:
        service = compose["services"][name]
        assert service["restart"] == "unless-stopped", name
        assert service["healthcheck"]["test"], name
    for name, service in compose["services"].items():
        assert service["logging"]["driver"] == "json-file", name
        assert service["logging"]["options"]["max-size"], name
        assert service["logging"]["options"]["max-file"], name


def test_only_caddy_publishes_ports_80_and_443(compose: dict[str, Any]) -> None:
    published = {name: s["ports"] for name, s in compose["services"].items() if "ports" in s}
    assert published == {"caddy": ["80:80", "443:443"]}


def test_app_images_come_from_the_on_premise_registry_by_commit_tag(compose: dict[str, Any]) -> None:
    images = {"keycloak": "keycloak", "api": "api", "migrate": "api", "web": "web", "agent": "agent", "mcp": "mcp"}
    for name, repo in {**images, "worker": "worker"}.items():
        assert compose["services"][name]["image"] == f"${{REGISTRY:?}}/${{REPOSITORY_PREFIX:?}}/{repo}:${{IMAGE_TAG:?}}"
    text = (ON_PREMISE_DIR / "compose.yaml").read_text(encoding="utf-8")
    assert not re.search(r"/smart-tutor/(api|web|keycloak|agent|mcp|worker):", text)


def test_deploy_script_renders_the_repository_prefix_from_the_host_settings() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "repository_prefix=$(param host/repository-prefix)" in script
    assert "\nREPOSITORY_PREFIX=$repository_prefix\n" in script
    # read before the env file is written, so a failed read stops the deploy before anything changes
    assert script.index("param host/repository-prefix") < script.index('cat > "$rendered"')


def test_data_lives_on_the_data_volume(compose: dict[str, Any]) -> None:
    assert "/data/postgres:/var/lib/postgresql/data" in compose["services"]["postgres"]["volumes"]
    assert "/data/caddy/data:/data" in compose["services"]["caddy"]["volumes"]


def test_keycloak_runs_in_production_mode_behind_caddy(compose: dict[str, Any]) -> None:
    keycloak = compose["services"]["keycloak"]
    assert keycloak["command"] == ["start", "--optimized", "--import-realm"]
    env = keycloak["environment"]
    assert env["KC_HOSTNAME"] == "https://${DOMAIN:?}/auth"
    assert env["KC_PROXY_HEADERS"] == "xforwarded"
    assert env["KC_DB_URL"] == "jdbc:postgresql://postgres:5432/keycloak"
    realm = keycloak["volumes"][0].split(":")[0]
    assert (ON_PREMISE_DIR / realm).resolve().is_file()


def test_api_reads_the_on_premise_ssm_path(compose: dict[str, Any]) -> None:
    env = compose["services"]["api"]["environment"]
    params = {k: v for k, v in env.items() if k.endswith("_PARAM")}
    assert params and all(v.startswith("${SSM_PATH:?}/") for v in params.values())
    assert env["SMART_TUTOR_KEYCLOAK_ISSUER"] == "https://${DOMAIN:?}/auth/realms/smart-tutor"
    assert env["SMART_TUTOR_ROOT_PATH"] == "/api"


def test_agent_mcp_and_worker_read_the_on_premise_ssm_path(compose: dict[str, Any]) -> None:
    for name in ("agent", "mcp", "worker"):
        env = compose["services"][name]["environment"]
        params = {k: v for k, v in env.items() if k.endswith("_PARAM")}
        assert all(v.startswith("${SSM_PATH:?}/") for v in params.values()), name
        assert env["SMART_TUTOR_AWS_REGION"] == "${AWS_REGION:?}", name
        assert env["HOME"] == "/tmp", name
    worker = compose["services"]["worker"]["environment"]
    assert worker["SMART_TUTOR_MAX_UPLOAD_MB_PARAM"] == "${SSM_PATH:?}/max-upload-mb"
    assert worker["SMART_TUTOR_MAX_PAGES_PARAM"] == "${SSM_PATH:?}/max-pages"


def test_worker_reads_the_on_premise_bucket_queue_and_database(compose: dict[str, Any]) -> None:
    env = compose["services"]["worker"]["environment"]
    assert env["SMART_TUTOR_DOCUMENTS_BUCKET"] == "${DOCUMENTS_BUCKET:?}"
    assert env["SMART_TUTOR_INGEST_QUEUE_URL"] == "${INGEST_QUEUE_URL:?}"
    assert env["SMART_TUTOR_DATABASE_URL"] == "${APP_DATABASE_URL:?}"
    assert env["SMART_TUTOR_EXTRACTION_TIMEOUT_SECONDS"] == "300"


def test_agent_and_mcp_reach_keycloak_and_each_other_inside_the_network(compose: dict[str, Any]) -> None:
    agent = compose["services"]["agent"]["environment"]
    mcp = compose["services"]["mcp"]["environment"]
    for env in (agent, mcp):
        assert env["SMART_TUTOR_KEYCLOAK_ISSUER"] == "https://${DOMAIN:?}/auth/realms/smart-tutor"
        assert env["SMART_TUTOR_KEYCLOAK_INTERNAL_URL"] == "http://keycloak:8080/auth/realms/smart-tutor"
        assert env["SMART_TUTOR_MCP_URL"] == "http://mcp:8000/mcp"
    assert (agent["SMART_TUTOR_KEYCLOAK_CLIENT_ID"], agent["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"]) == (
        "smart-tutor-api",
        "${API_CLIENT_SECRET:?}",
    )
    assert (mcp["SMART_TUTOR_KEYCLOAK_CLIENT_ID"], mcp["SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"]) == (
        "rag-mcp",
        "${MCP_CLIENT_SECRET:?}",
    )
    assert mcp["SMART_TUTOR_KEYCLOAK_AUDIENCE"] == "rag-mcp"
    assert mcp["SMART_TUTOR_MCP_PORT"] == "8000"
    assert compose["services"]["api"]["depends_on"]["agent"] == {"condition": "service_started"}
    assert compose["services"]["agent"]["depends_on"]["mcp"] == {"condition": "service_started"}


def test_worker_runs_isolated_as_non_root_on_a_read_only_root(compose: dict[str, Any]) -> None:
    worker = compose["services"]["worker"]
    assert worker["user"] == "10001:10001"
    assert worker["read_only"] is True
    assert worker["tmpfs"] == ["/tmp:size=64m"]
    assert worker["cap_drop"] == ["ALL"]
    assert worker["security_opt"] == ["no-new-privileges:true"]
    assert worker["cpus"] == 1.0
    assert worker["mem_limit"] == "1536m"
    assert worker["pids_limit"] == 256  # room for one extraction child process per PDF
    assert worker["stop_grace_period"] == "60s"
    assert "smart_tutor.apps.worker" in " ".join(worker["healthcheck"]["test"])


def _squid_conf(compose: dict[str, Any]) -> list[str]:
    conf = compose["services"]["egress-proxy"]["environment"]["SQUID_CONF"]
    return [line.strip() for line in conf.splitlines() if line.strip() and not line.strip().startswith("#")]


def test_worker_reaches_only_postgres_phoenix_and_the_egress_proxy(compose: dict[str, Any]) -> None:
    assert compose["networks"]["worker"] == {"internal": True}  # no route out of the VM, no external DNS
    assert compose["services"]["worker"]["networks"] == ["worker"]
    on_worker_network = {n for n, s in compose["services"].items() if "worker" in s.get("networks", [])}
    assert on_worker_network == {"worker", "postgres", "egress-proxy", "phoenix"}
    # Every other service keeps the default network only.
    assert compose["services"]["postgres"]["networks"] == ["default", "worker"]
    assert compose["services"]["egress-proxy"]["networks"] == ["default", "worker"]
    assert compose["services"]["phoenix"]["networks"] == ["default", "worker"]
    for name, service in compose["services"].items():
        if name not in on_worker_network:
            assert "networks" not in service, name
    env = compose["services"]["worker"]["environment"]
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://egress-proxy:3128"
    assert env["AWS_METADATA_SERVICE_TIMEOUT"] == "2"
    assert env["AWS_METADATA_SERVICE_NUM_ATTEMPTS"] == "3"
    assert compose["services"]["worker"]["depends_on"]["egress-proxy"] == {"condition": "service_healthy"}


def test_egress_proxy_allows_only_the_workers_aws_endpoints_and_imds(compose: dict[str, Any]) -> None:
    lines = _squid_conf(compose)
    acls = {line.split()[1]: line.split()[2:] for line in lines if line.startswith("acl ")}
    assert acls["aws"] == [
        "dstdomain",
        "-n",  # no reverse lookup: an IP literal never matches a name
        "${DOCUMENTS_BUCKET:?}.s3.amazonaws.com",
        "${DOCUMENTS_BUCKET:?}.s3.${AWS_REGION:?}.amazonaws.com",
        "sqs.${AWS_REGION:?}.amazonaws.com",
        "ssm.${AWS_REGION:?}.amazonaws.com",
        "bedrock-runtime.${AWS_REGION:?}.amazonaws.com",
    ]
    assert acls["imds"] == ["dstdomain", "-n", "169.254.169.254"]
    assert acls["tls"] == ["port", "443"] and acls["http"] == ["port", "80"]
    rules = [line for line in lines if line.startswith("http_access ")]
    assert rules == [
        "http_access allow CONNECT aws tls",
        "http_access allow CONNECT langsmith tls",
        "http_access allow !CONNECT imds http",
        "http_access deny all",
    ]
    assert "forwarded_for delete" in lines  # IMDSv2 refuses a token request with X-Forwarded-For
    assert "via off" in lines
    assert "cache deny all" in lines


def test_egress_proxy_runs_unprivileged_on_a_read_only_root(compose: dict[str, Any]) -> None:
    proxy = compose["services"]["egress-proxy"]
    # Pinned by digest: the tag is Canonical's mutable edge channel.
    assert proxy["image"] == (
        "ubuntu/squid:6.6-24.04_edge@sha256:8a3baed477e2c282ab8aa5edad442f69873246964f225c5c2ae8364b6610963c"
    )
    assert proxy["pids_limit"] == 64
    assert proxy["user"] == "proxy"
    assert proxy["read_only"] is True
    assert proxy["cap_drop"] == ["ALL"]
    assert proxy["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in proxy
    # The config is an environment variable, so a new bucket or region recreates the container.
    assert "SQUID_CONF" in " ".join(proxy["entrypoint"])


def test_agent_and_mcp_run_on_a_read_only_root_without_capabilities(compose: dict[str, Any]) -> None:
    for name in ("agent", "mcp"):
        service = compose["services"][name]
        assert service["read_only"] is True, name
        assert service["tmpfs"] == ["/tmp:size=64m"], name
        assert service["cap_drop"] == ["ALL"], name
        assert service["security_opt"] == ["no-new-privileges:true"], name
        assert service["mem_limit"] == "512m", name


def test_caddy_routes_one_origin_by_path() -> None:
    caddyfile = (ON_PREMISE_DIR / "Caddyfile").read_text(encoding="utf-8")
    assert "{$SMART_TUTOR_DOMAIN} {" in caddyfile
    routes = re.findall(r"(handle(?:_path)?)( /\S+)? \{(?:\s+#.*)*\s+reverse_proxy (\S+)", caddyfile)
    assert routes == [
        ("handle", " /api/*", "api:8080"),
        ("handle", " /auth/*", "keycloak:8080"),
        ("handle_path", " /phoenix/*", "phoenix:6006"),
        ("handle", "", "web:8080"),
    ]
    assert "redir /phoenix /phoenix/" in caddyfile
    assert "protocols h1 h2" in caddyfile  # no HTTP/3: UDP 443 is closed


DEPLOY_SCRIPT = ON_PREMISE_DIR / "deploy.sh"


def test_deploy_script_keeps_secrets_out_of_output_and_files_root_only() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert "set -x" not in script.replace("never add `set -x`", "")
    assert "compose config" not in script.replace("`docker compose config`", "")
    assert script.index("umask 077") < script.index('cat > "$rendered"')
    # Passwords reach psql through its environment (\getenv), not its command line.
    assert "\\\\getenv app_password APP_DB_PASSWORD" in script


def test_no_credential_shaped_url_is_in_the_repository() -> None:
    # GitGuardian's generic-password detector flags user:password@host even when the password is a ${PLACEHOLDER}.
    for path in (p for p in ON_PREMISE_DIR.rglob("*") if p.is_file()):
        assert not re.search(r"://[^\s/:@]+:[^\s/@]+@", path.read_text(encoding="utf-8")), path


def test_deploy_script_points_a_duckdns_name_at_the_instance_before_caddy_starts() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = script.index("if [[ $domain == *.duckdns.org ]]")
    update = script[start : script.index("\nfi\n", start)]
    assert "secret duckdns/token" in update
    # The token reaches curl on stdin (-K -), never a command line; only "OK" counts as updated.
    assert 'curl -sS --max-time 20 -K - <<<"url = ' in update
    assert "[[ $duckdns_answer == OK ]]" in update
    assert "Warning: could not update" in update and "exit" not in update  # warns, never fails the deploy
    assert start < script.index("up -d --wait --wait-timeout")


def test_deploy_script_points_the_sign_in_client_at_the_domain() -> None:
    # Keycloak imports the realm once, so a domain change must reach the existing smart-tutor-web client (#154).
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = script.index("clientId=smart-tutor-web")
    sync = script[start : script.index("id=\\$(learner_id)", start)]
    assert '!= "https://$domain"' in sync
    assert '-s "redirectUris=[\\"https://$domain/*\\"]"' in sync
    assert '-s "webOrigins=[\\"https://$domain\\"]"' in sync
    assert '-s "attributes.\\"post.logout.redirect.uris\\"=https://$domain/*"' in sync
    assert script.index("exec -T keycloak bash -s <<EOF") < start


def test_deploy_script_migrates_before_it_starts_the_new_tag() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script.index("run --rm migrate") < script.index("up -d --wait --wait-timeout")


def test_deploy_script_checks_the_worker_and_the_inner_services_after_starting_them() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script.index("here=") < script.index('source "$here/check-worker.sh"')
    check = script[script.index("up -d --wait --wait-timeout 900 --remove-orphans") :]
    assert check.index("check_worker || exit 1") < check.index("exec -T api python")
    assert "http://agent:8080/healthz" in check
    assert "http://mcp:8000/mcp" in check and "401" in check


CHECK_WORKER = ON_PREMISE_DIR / "check-worker.sh"


def _commands(script: str) -> str:
    return "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))


def test_check_worker_is_a_function_the_caller_sources() -> None:
    script = CHECK_WORKER.read_text(encoding="utf-8")
    assert not script.startswith("#!")  # sourced, never run on its own
    assert "check_worker() {" in script
    # It returns, so the caller exits (`set -e` doesn't apply inside `check_worker || exit 1`).
    assert "exit" not in _commands(script)


def test_check_worker_asserts_the_running_workers_isolation() -> None:
    check = CHECK_WORKER.read_text(encoding="utf-8")
    assert "ps -q worker" in check
    for fragment in ("docker inspect", ".Config.User", "10001:10001", "ReadonlyRootfs", "CapDrop", "no-new-privileges"):
        assert fragment in check, fragment
    # A worker that isn't isolated is stopped before the check fails, so it parses no more untrusted PDFs.
    failed = check[check.index("The worker is not isolated") :]
    assert failed.index('docker stop "$worker"') < failed.index("return 1")
    assert check.index("Checking the worker's isolation") < check.index("Checking the worker's egress")


def test_check_worker_proves_the_workers_egress_block_and_stops_a_leaking_worker() -> None:
    check = CHECK_WORKER.read_text(encoding="utf-8")
    assert '"${compose[@]}" exec -T worker python - <"$here/check-egress.py" || status=$?' in check
    egress = check[check.index("Checking the worker's egress") :]
    egress = egress[: egress.index("esac")]
    # Exit 2 (AWS or Postgres unreachable) only fails the check; any other status stops the worker first.
    unreachable = egress[egress.index("2)") : egress.index(";;", egress.index("2)"))]
    assert "return 1" in unreachable and "docker stop" not in unreachable
    assert "The worker cannot reach a destination it needs (see above)" in unreachable
    leaked = egress[egress.index("*)") :]
    assert leaked.index('docker stop "$worker"') < leaked.index("return 1")
    assert "Stopped the worker: the egress check found a leak or could not run (see above)" in leaked


GOOD_ISOLATION = '10001:10001|true|["ALL"]|["no-new-privileges:true"]'
FAKE_DOCKER = """
here=$(mktemp -d)
trap 'rm -rf "$here"' EXIT
: >"$here/check-egress.py"
fake_compose() {
  case "$*" in
    'ps -q worker') printf '%s\\n' "$WORKER" ;;
    'exec -T worker python -') echo 'egress check ran'; return "$EGRESS_STATUS" ;;
    *) echo "unexpected compose $*" >&2; return 99 ;;
  esac
}
docker() {
  case $1 in
    inspect) printf '%s\\n' "$ISOLATION" ;;
    stop) echo "docker stop $2" >&2 ;;
    *) echo "unexpected docker $*" >&2; return 99 ;;
  esac
}
compose=(fake_compose)
"""


def _run_check_worker(worker: str, isolation: str, egress_status: int) -> subprocess.CompletedProcess[bytes]:
    """Sources check-worker.sh under `set -euo pipefail`, as the callers do, with fake `docker` and compose."""
    program = "\n".join(
        [
            "set -euo pipefail",
            f"WORKER={shlex.quote(worker)} ISOLATION={shlex.quote(isolation)} EGRESS_STATUS={egress_status}",
            FAKE_DOCKER,
            CHECK_WORKER.read_text(encoding="utf-8"),
            "check_worker || exit 1",
            "echo 'the caller goes on'",
        ]
    )
    # On stdin: on Windows, `bash` may be WSL's, which can't open a Windows path.
    return subprocess.run(["bash"], input=program.encode(), capture_output=True, check=False)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize(
    ("worker", "isolation", "egress_status", "code", "stopped", "message"),
    [
        ("abc123", GOOD_ISOLATION, 0, 0, False, ""),
        ("abc123", GOOD_ISOLATION, 2, 1, False, "The worker cannot reach a destination it needs"),
        ("abc123", GOOD_ISOLATION, 1, 1, True, "the egress check found a leak or could not run"),
        ("abc123", GOOD_ISOLATION, 137, 1, True, "the egress check found a leak or could not run"),
        ("abc123", "0:0|false|null|null", 0, 1, True, "The worker is not isolated: runs as '0:0'"),
        ("", GOOD_ISOLATION, 0, 1, False, "The worker container is not running"),
    ],
    ids=["passes", "unreachable", "leak", "crash", "not-isolated", "not-running"],
)
def test_check_worker_fails_the_caller_and_stops_a_worker_that_may_leak(
    worker: str, isolation: str, egress_status: int, code: int, stopped: bool, message: str
) -> None:
    run = _run_check_worker(worker, isolation, egress_status)
    out, err = run.stdout.decode(), run.stderr.decode()
    assert run.returncode == code, err
    assert ("the caller goes on" in out) == (code == 0)
    assert ("docker stop abc123" in err) == stopped
    assert message in err
    assert "unexpected" not in err
    assert ("egress check ran" in out) == (worker != "" and isolation == GOOD_ISOLATION)


ENSURE_HEALTHY = ON_PREMISE_DIR / "ensure-healthy.sh"
SCRIPTS = [
    DEPLOY_SCRIPT,
    ENSURE_HEALTHY,
    CHECK_WORKER,
    *(ON_PREMISE_DIR / name for name in ("backup.sh", "restore.sh", "report-failure.sh")),
]
VM_FILES = [*SCRIPTS, ON_PREMISE_DIR / "check-egress.py"]
SYSTEMD_DIR = ON_PREMISE_DIR / "systemd"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script: Path) -> None:
    # On stdin: on Windows, `bash` may be WSL's, which can't open a Windows path.
    subprocess.run(["bash", "-n"], input=script.read_bytes(), check=True)


def test_files_the_vm_runs_keep_lf_line_endings() -> None:
    for path in (*VM_FILES, ON_PREMISE_DIR / "compose.yaml", ON_PREMISE_DIR / "Caddyfile", *SYSTEMD_DIR.iterdir()):
        assert b"\r\n" not in path.read_bytes(), path


# --- monitoring and patching (#152)--------------------------------------------------------------------------------


def _alarm(t: Template, metric_name: str) -> dict[str, Any]:
    (alarm,) = (
        a["Properties"]
        for a in t.find_resources("AWS::CloudWatch::Alarm").values()
        if a["Properties"]["MetricName"] == metric_name
    )
    return alarm


def test_alarms_email_the_budget_recipients(t: Template) -> None:
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    t.has_resource_properties("AWS::SNS::Topic", {"TopicName": "smart-tutor-on-premise-prod-alerts"})
    subscriptions = [s["Properties"] for s in t.find_resources("AWS::SNS::Subscription").values()]
    assert [(s["Protocol"], s["Endpoint"]) for s in subscriptions] == [("email", "dtrungthao@gmail.com")]
    assert all(s["TopicArn"] == {"Ref": topic_id} for s in subscriptions)


def test_system_status_check_alarm_recovers_the_instance_and_emails(t: Template) -> None:
    (instance_id,) = t.find_resources("AWS::EC2::Instance")
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    alarm = _alarm(t, "StatusCheckFailed_System")

    assert alarm["Namespace"] == "AWS/EC2"
    assert alarm["Dimensions"] == [{"Name": "InstanceId", "Value": {"Ref": instance_id}}]
    assert alarm["ComparisonOperator"] == "GreaterThanOrEqualToThreshold" and alarm["Threshold"] == 1
    actions = json.dumps(alarm["AlarmActions"])
    assert ":automate:" in actions and ":ec2:recover" in actions
    assert {"Ref": topic_id} in alarm["AlarmActions"]


def test_uptime_check_probes_the_api_health_route_over_https_on_the_domain(t: Template) -> None:
    (check,) = t.find_resources("AWS::Route53::HealthCheck").values()
    config = check["Properties"]["HealthCheckConfig"]

    assert config["Type"] == "HTTPS"
    assert config["Port"] == 443
    assert config["ResourcePath"] == "/api/healthz"
    # Through DNS, as a learner reaches it: a lapsed DuckDNS name fails the check too.
    assert config["FullyQualifiedDomainName"] == "smart-tutor.duckdns.org"
    assert "IPAddress" not in config


def test_uptime_check_follows_the_sslip_io_fallback() -> None:
    t = host(**{"smart-tutor:on-premise-domain": ""})
    (check,) = t.find_resources("AWS::Route53::HealthCheck").values()
    (eip_id,) = t.find_resources("AWS::EC2::EIP")
    assert check["Properties"]["HealthCheckConfig"]["FullyQualifiedDomainName"] == {
        "Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]
    }


def test_uptime_alarm_emails_when_the_check_fails_and_when_it_recovers(t: Template) -> None:
    (check_id,) = t.find_resources("AWS::Route53::HealthCheck")
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    alarm = _alarm(t, "HealthCheckStatus")

    assert alarm["Namespace"] == "AWS/Route53"
    assert alarm["Dimensions"] == [{"Name": "HealthCheckId", "Value": {"Ref": check_id}}]
    assert alarm["Statistic"] == "Minimum"
    assert alarm["ComparisonOperator"] == "LessThanThreshold" and alarm["Threshold"] == 1
    assert alarm["AlarmActions"] == [{"Ref": topic_id}]
    assert alarm["OKActions"] == [{"Ref": topic_id}]


def test_patch_baseline_approves_security_patches_for_the_tagged_host(t: Template) -> None:
    (baseline,) = t.find_resources("AWS::SSM::PatchBaseline").values()
    props = baseline["Properties"]
    assert props["OperatingSystem"] == "AMAZON_LINUX_2023"
    assert props["PatchGroups"] == ["smart-tutor-on-premise-prod"]
    (rule,) = props["ApprovalRules"]["PatchRules"]
    filters = {f["Key"]: f["Values"] for f in rule["PatchFilterGroup"]["PatchFilters"]}
    assert filters["CLASSIFICATION"] == ["Security"]
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    assert {"Key": "PatchGroup", "Value": "smart-tutor-on-premise-prod"} in instance["Properties"]["Tags"]


def test_weekly_maintenance_window_patches_the_host_then_checks_the_services(t: Template) -> None:
    (window_id,) = t.find_resources("AWS::SSM::MaintenanceWindow")
    t.has_resource_properties(
        "AWS::SSM::MaintenanceWindow",
        {"Schedule": "cron(0 4 ? * SUN *)", "ScheduleTimezone": "Asia/Ho_Chi_Minh", "AllowUnassociatedTargets": False},
    )
    (instance_id,) = t.find_resources("AWS::EC2::Instance")
    (target_id,) = t.find_resources("AWS::SSM::MaintenanceWindowTarget")
    t.has_resource_properties(
        "AWS::SSM::MaintenanceWindowTarget",
        {
            "WindowId": {"Ref": window_id},
            "ResourceType": "INSTANCE",
            "Targets": [{"Key": "InstanceIds", "Values": [{"Ref": instance_id}]}],
        },
    )
    tasks = sorted(
        (task["Properties"] for task in t.find_resources("AWS::SSM::MaintenanceWindowTask").values()),
        key=lambda task: task["Priority"],
    )
    assert [task["TaskArn"] for task in tasks] == ["AWS-RunPatchBaseline", "AWS-RunShellScript"]
    assert all(task["Targets"] == [{"Key": "WindowTargetIds", "Values": [{"Ref": target_id}]}] for task in tasks)
    patch, check = (task["TaskInvocationParameters"]["MaintenanceWindowRunCommandParameters"] for task in tasks)
    assert patch["Parameters"] == {"Operation": ["Install"], "RebootOption": ["RebootIfNeeded"]}
    (command,) = check["Parameters"]["commands"]
    assert command.endswith("; bash /opt/smart-tutor/on-premise/ensure-healthy.sh")
    assert "redeploy the current tag" in command  # a VM deployed before #152 doesn't have the script yet
    # The check runs after the patching even when the window's time is up.
    assert all(task["CutoffBehavior"] == "CONTINUE_TASK" for task in tasks)


def test_a_failed_maintenance_window_emails(t: Template) -> None:
    (window_id,) = t.find_resources("AWS::SSM::MaintenanceWindow")
    (topic_id,) = t.find_resources("AWS::SNS::Topic")
    (rule,) = t.find_resources("AWS::Events::Rule").values()
    pattern = rule["Properties"]["EventPattern"]

    assert pattern["source"] == ["aws.ssm"]
    assert pattern["detail-type"] == ["Maintenance Window Execution State-change Notification"]
    assert pattern["detail"] == {"window-id": [{"Ref": window_id}], "status": ["FAILED", "TIMED_OUT"]}
    assert [target["Arn"] for target in rule["Properties"]["Targets"]] == [{"Ref": topic_id}]


def test_ensure_healthy_starts_what_is_down_and_waits_for_health() -> None:
    script = ENSURE_HEALTHY.read_text(encoding="utf-8")
    assert script.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in script
    assert "up -d --wait --wait-timeout" in script
    # It brings back what the last deploy ran: no pull, no migration.
    commands = _commands(script)
    assert " pull" not in commands and "migrate" not in commands


def test_ensure_healthy_re_proves_the_workers_isolation_and_egress() -> None:
    # Otherwise the patch window would restart a worker that a deploy stopped, and report it healthy.
    script = ENSURE_HEALTHY.read_text(encoding="utf-8")
    assert script.index("here=") < script.index('source "$here/check-worker.sh"')
    started = script.index("up -d --wait --wait-timeout")
    assert started < script.index("check_worker || exit 1") < script.index("Every service is healthy")


# --- backups (#151) ------------------------------------------------------------------------------------------------


def _unit(name: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    section: dict[str, str] = {}
    for line in (SYSTEMD_DIR / name).read_text(encoding="utf-8").splitlines():
        if line.startswith("["):
            section = sections.setdefault(line.strip("[]"), {})
        elif "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            section[key] = value
    return sections


def test_pg_dump_runs_the_servers_own_pg_dump_against_postgres(compose: dict[str, Any]) -> None:
    pg_dump = compose["services"]["pg-dump"]
    assert pg_dump["image"] == compose["services"]["postgres"]["image"]
    assert pg_dump["entrypoint"][:3] == ["pg_dump", "--host=postgres", "--username=postgres"]
    assert "--format=custom" in pg_dump["entrypoint"]
    assert pg_dump["environment"] == {"PGPASSWORD": "${POSTGRES_PASSWORD:?}"}
    assert pg_dump["volumes"] == ["/data/backups:/backups"]


def test_backup_dumps_both_databases_with_compose_run_and_uploads_them_under_the_backups_prefix() -> None:
    script = (ON_PREMISE_DIR / "backup.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "for db in smart_tutor keycloak" in script
    assert "run --rm -T pg-dump" in script
    assert 's3://$bucket/backups/postgres/$stamp/$db.dump' in script
    # Every dump is written before any is uploaded, so a failed night leaves no half backup.
    assert script.index("run --rm -T pg-dump") < script.index("aws s3 cp")
    assert "trap" in script and "rm -rf" in script  # local copies don't pile up on /data


def test_restore_stops_the_services_and_restores_both_databases_from_one_backup() -> None:
    script = (ON_PREMISE_DIR / "restore.sh").read_text(encoding="utf-8")
    assert script.index('"${compose[@]}" stop\n') < script.index("pg_restore -U")
    assert "pg_restore -U postgres -d postgres --clean --if-exists --create --exit-on-error" in script
    assert "for db in smart_tutor keycloak" in script


def test_backup_timer_runs_nightly_and_catches_up_after_downtime() -> None:
    timer = _unit("smart-tutor-backup.timer")["Timer"]
    assert timer["OnCalendar"] == "*-*-* 20:00:00 UTC"  # 03:00 ICT, an hour after the snapshot
    assert timer["Persistent"] == "true"
    assert _unit("smart-tutor-backup.timer")["Install"]["WantedBy"] == "timers.target"


def test_backup_service_runs_the_script_and_reports_a_failure() -> None:
    service = _unit("smart-tutor-backup.service")
    assert service["Service"]["Type"] == "oneshot"
    assert service["Service"]["ExecStart"] == "/usr/bin/bash /opt/smart-tutor/on-premise/backup.sh"
    assert service["Unit"]["OnFailure"] == "smart-tutor-job-failed@%N.service"
    assert "docker.service" in service["Unit"]["Requires"]


def test_a_failed_job_publishes_the_metric_the_alarm_watches() -> None:
    unit = _unit("smart-tutor-job-failed@.service")
    assert unit["Service"]["ExecStart"] == "/usr/bin/bash /opt/smart-tutor/on-premise/report-failure.sh %i"
    script = (ON_PREMISE_DIR / "report-failure.sh").read_text(encoding="utf-8")
    assert "--namespace SmartTutor/OnPremise --metric-name JobFailed" in script
    assert '--dimensions "Job=$job"' in script


def test_deploy_installs_and_enables_every_timer() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'install -m 644 "$here"/systemd/* /etc/systemd/system/' in script
    assert "systemctl daemon-reload" in script
    assert 'for timer in "$here"/systemd/*.timer' in script
    assert script.index("up -d --wait --wait-timeout") < script.index("systemctl daemon-reload")


LANGSMITH_HOST = "api.smith.langchain.com"


@pytest.mark.parametrize("service", ["agent", "worker"])
def test_agent_and_worker_trace_into_the_on_premise_project(compose: dict[str, Any], service: str) -> None:
    env = compose["services"][service]["environment"]
    assert env["LANGSMITH_TRACING"] == "${LANGSMITH_TRACING:?}"
    assert env["LANGSMITH_API_KEY"] == "${LANGSMITH_API_KEY}"  # empty while tracing is off
    assert env["LANGSMITH_PROJECT"] == "smart-tutor-on-premise"  # the worker adds -ingestion
    assert env["LANGSMITH_TRACING_SAMPLING_RATE"] == "${TRACE_SAMPLING_RATE:?}"
    assert env["SMART_TUTOR_LEARNER_HASH_KEY"] == "${LEARNER_HASH_KEY:?}"


@pytest.mark.parametrize("service", ["api", "mcp"])
def test_services_that_make_no_model_calls_of_their_own_do_not_trace(compose: dict[str, Any], service: str) -> None:
    assert not [k for k in compose["services"][service]["environment"] if k.startswith("LANGSMITH_")]


def test_egress_proxy_allows_langsmith_by_exact_name_on_443_only(compose: dict[str, Any]) -> None:
    lines = _squid_conf(compose)
    acls = {line.split()[1]: line.split()[2:] for line in lines if line.startswith("acl ")}
    assert acls["langsmith"] == ["dstdomain", "-n", LANGSMITH_HOST]
    allows = [line for line in lines if line.startswith("http_access allow")]
    assert allows == ["http_access allow CONNECT aws tls", "http_access allow CONNECT langsmith tls",
                      "http_access allow !CONNECT imds http"]


def test_deploy_script_renders_the_tracing_settings_and_turns_tracing_off_without_the_api_key() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "learner_hash_key=$(secret langsmith/learner-hash-key)" in script
    assert "trace_sampling_rate=$(param trace-sampling-rate)" in script
    tracing = script[script.index("langsmith_api_key="):script.index("umask 077")]
    assert "secret langsmith/api-key 2>/dev/null" in tracing
    assert "langsmith_tracing=false" in tracing and "langsmith_tracing=true" in tracing
    assert "$prefix/langsmith/api-key" in tracing and ">&2" in tracing  # the warning names the secret
    for line in ("LANGSMITH_TRACING=$langsmith_tracing", "LANGSMITH_API_KEY=$langsmith_api_key",
                 "TRACE_SAMPLING_RATE=$trace_sampling_rate", "LEARNER_HASH_KEY=$learner_hash_key"):
        assert line in script


PHOENIX_IMAGE = "arizephoenix/phoenix:version-20.16.0-nonroot"


def test_phoenix_runs_unprivileged_on_a_read_only_root_with_its_traces_in_postgres(compose: dict[str, Any]) -> None:
    phoenix = compose["services"]["phoenix"]
    assert phoenix["image"] == PHOENIX_IMAGE
    assert phoenix["user"] == "65532:65532"
    assert phoenix["read_only"] is True
    assert phoenix["cap_drop"] == ["ALL"]
    assert phoenix["security_opt"] == ["no-new-privileges:true"]
    assert "ports" not in phoenix
    env = phoenix["environment"]
    assert (env["PHOENIX_POSTGRES_HOST"], env["PHOENIX_POSTGRES_USER"], env["PHOENIX_POSTGRES_DB"]) == (
        "postgres",
        "phoenix",
        "phoenix",
    )
    assert env["PHOENIX_POSTGRES_PASSWORD"] == "${PHOENIX_DB_PASSWORD:?}"
    assert "PHOENIX_SQL_DATABASE_URL" not in env
    assert env["PHOENIX_WORKING_DIR"].startswith("/tmp/")  # the only writable place
    assert phoenix["depends_on"]["postgres"] == {"condition": "service_healthy"}
    assert "/healthz" in " ".join(phoenix["healthcheck"]["test"])


def test_phoenix_is_served_at_slash_phoenix_with_sign_in_and_180_day_retention(compose: dict[str, Any]) -> None:
    env = compose["services"]["phoenix"]["environment"]
    assert env["PHOENIX_HOST_ROOT_PATH"] == "/phoenix"
    assert env["PHOENIX_ROOT_URL"] == "https://${DOMAIN:?}/phoenix"
    assert env["PHOENIX_ENABLE_AUTH"] == "true"
    assert env["PHOENIX_ENABLE_STRONG_PASSWORD_POLICY"] == "true"
    assert env["PHOENIX_USE_SECURE_COOKIES"] == "true"
    assert env["PHOENIX_SECRET"] == "${PHOENIX_SECRET:?}"
    assert env["PHOENIX_DEFAULT_ADMIN_INITIAL_PASSWORD"] == "${PHOENIX_ADMIN_PASSWORD:?}"
    assert env["PHOENIX_DEFAULT_RETENTION_POLICY_DAYS"] == "180"  # D25
    # Production traces hold learners' questions: no analytics pixels, no assistant sending them to an LLM provider.
    assert env["PHOENIX_TELEMETRY_ENABLED"] == "false"
    assert env["PHOENIX_DISABLE_AGENT_ASSISTANT"] == "true"
    assert env["PHOENIX_ENABLE_MCP_SERVER"] == "false"  # no /mcp mount
    assert env["PHOENIX_ALLOWED_SANDBOX_PROVIDERS"] == "NONE"  # Phoenix's kill switch: no sandbox provider


def test_deploy_script_bootstraps_the_phoenix_role_and_renders_its_secrets() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    for read in ("secret db/phoenix", "secret phoenix/secret", "secret phoenix/admin-password"):
        assert read in script and script.index(read) < script.index('cat > "$rendered"'), read
    for line in (
        "PHOENIX_DB_PASSWORD=$phoenix_db_password",
        "PHOENIX_SECRET=$phoenix_secret",
        "PHOENIX_ADMIN_PASSWORD=$phoenix_admin_password",
    ):
        assert f"\n{line}\n" in script, line
    assert "\\\\getenv phoenix_password PHOENIX_DB_PASSWORD" in script  # never on a command line
    assert 'cat "$here/phoenix-db-bootstrap.sql"' in script
    assert "-v phoenix_user=phoenix -v phoenix_db=phoenix" in script
    postgres = yaml.safe_load((ON_PREMISE_DIR / "compose.yaml").read_text(encoding="utf-8"))["services"]["postgres"]
    assert postgres["environment"]["PHOENIX_DB_PASSWORD"] == "${PHOENIX_DB_PASSWORD:?}"


def test_phoenix_bootstrap_is_idempotent_and_on_premise_only() -> None:
    sql = (ON_PREMISE_DIR / "phoenix-db-bootstrap.sql").read_text(encoding="utf-8")
    assert "\\set ON_ERROR_STOP on" in sql
    assert "WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'phoenix_user') \\gexec" in sql
    assert "WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'phoenix_db') \\gexec" in sql
    assert "ALTER ROLE :\"phoenix_user\" WITH LOGIN PASSWORD :'phoenix_password';" in sql
    assert "REVOKE CONNECT ON DATABASE :\"phoenix_db\" FROM PUBLIC;" in sql
    helm = (ON_PREMISE_DIR.parent / "helm/smart-tutor/files/db-bootstrap.sql").read_text(encoding="utf-8")
    assert "phoenix" not in helm  # native-cloud is out of scope (ADR 0017)


def test_nightly_backup_leaves_the_phoenix_database_out() -> None:
    script = (ON_PREMISE_DIR / "backup.sh").read_text(encoding="utf-8")
    assert re.findall(r"for db in ([^;]+);", script) == ["smart_tutor keycloak", "smart_tutor keycloak"]
    assert "phoenix" not in _commands(script)
