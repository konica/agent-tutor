"""The on-premise Host stack and the files it runs on the VM (#148, PRD §9.12, ADR 0012)."""

import json
import re
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
    assert all(f"repository/smart-tutor/{s}" in pull for s in ("api", "web", "keycloak", "agent", "mcp", "worker"))
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
    (default_volume,) = host().find_resources("AWS::EC2::Volume").values()
    assert "SnapshotId" not in default_volume["Properties"]


def test_a_new_data_volume_replaces_the_instance_so_it_attaches_at_first_boot() -> None:
    # The user data names the volume and runs only at first boot, so a changed user data must replace the instance.
    (before,) = host().find_resources("AWS::EC2::Instance")
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


def test_domain_defaults_to_the_elastic_ip_on_sslip_io(t: Template) -> None:
    (eip_id,) = t.find_resources("AWS::EC2::EIP")
    assert _parameter(t, "domain") == {"Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]}


def test_domain_is_a_setting() -> None:
    assert _parameter(host(**{"smart-tutor:on-premise-domain": "smart-tutor.duckdns.org"}), "domain") == (
        "smart-tutor.duckdns.org"
    )


def test_deploy_settings_name_on_premise_resources(t: Template) -> None:
    assert "smart-tutor-on-premise-documents-" in json.dumps(_parameter(t, "documents-bucket"))
    assert "/smart-tutor-on-premise-ingest" in json.dumps(_parameter(t, "ingest-queue-url"))
    assert ".dkr.ecr." in json.dumps(_parameter(t, "registry"))
    assert "s3://" in json.dumps(_parameter(t, "bundle"))


def test_database_and_test_learner_secrets_are_generated(t: Template) -> None:
    secrets = {
        s["Properties"]["Name"]: s["Properties"] for s in t.find_resources("AWS::SecretsManager::Secret").values()
    }
    assert set(secrets) == {
        "smart-tutor-on-premise/db/postgres",
        "smart-tutor-on-premise/db/app",
        "smart-tutor-on-premise/db/keycloak",
        "smart-tutor-on-premise/keycloak/test-learner",
    }
    assert all("SecretString" not in s and s["GenerateSecretString"]["ExcludePunctuation"] for s in secrets.values())
    learner = secrets["smart-tutor-on-premise/keycloak/test-learner"]["GenerateSecretString"]
    assert learner["GenerateStringKey"] == "password"
    assert json.loads(learner["SecretStringTemplate"])["username"] == "test-learner@example.com"


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


LONG_RUNNING = {"postgres", "keycloak", "api", "web", "caddy", "agent", "mcp", "worker", "egress-proxy"}


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


def test_app_images_come_from_ecr_by_commit_tag(compose: dict[str, Any]) -> None:
    images = {"keycloak": "keycloak", "api": "api", "migrate": "api", "web": "web", "agent": "agent", "mcp": "mcp"}
    for name, repo in {**images, "worker": "worker"}.items():
        assert compose["services"][name]["image"] == f"${{REGISTRY:?}}/smart-tutor/{repo}:${{IMAGE_TAG:?}}"


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


def test_worker_reaches_only_postgres_and_the_egress_proxy(compose: dict[str, Any]) -> None:
    assert compose["networks"]["worker"] == {"internal": True}  # no route out of the VM, no external DNS
    assert compose["services"]["worker"]["networks"] == ["worker"]
    on_worker_network = {n for n, s in compose["services"].items() if "worker" in s.get("networks", [])}
    assert on_worker_network == {"worker", "postgres", "egress-proxy"}
    # Every other service keeps the default network only.
    assert compose["services"]["postgres"]["networks"] == ["default", "worker"]
    assert compose["services"]["egress-proxy"]["networks"] == ["default", "worker"]
    for name, service in compose["services"].items():
        if name not in on_worker_network:
            assert "networks" not in service, name
    env = compose["services"]["worker"]["environment"]
    assert env["HTTPS_PROXY"] == env["HTTP_PROXY"] == "http://egress-proxy:3128"
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
        "http_access allow !CONNECT imds http",
        "http_access deny all",
    ]
    assert "forwarded_for delete" in lines  # IMDSv2 refuses a token request with X-Forwarded-For
    assert "via off" in lines
    assert "cache deny all" in lines


def test_egress_proxy_runs_unprivileged_on_a_read_only_root(compose: dict[str, Any]) -> None:
    proxy = compose["services"]["egress-proxy"]
    assert proxy["image"] == "ubuntu/squid:6.6-24.04_edge"
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
    routes = re.findall(r"handle( /\S+)? \{(?:\s+#.*)*\s+reverse_proxy (\S+)", caddyfile)
    assert routes == [(" /api/*", "api:8080"), (" /auth/*", "keycloak:8080"), ("", "web:8080")]
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


def test_deploy_script_migrates_before_it_starts_the_new_tag() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script.index("run --rm migrate") < script.index("up -d --wait --wait-timeout")


def test_deploy_script_asserts_the_running_workers_isolation_and_the_inner_services() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    started = script.index("up -d --wait --wait-timeout")
    check = script[started:]
    assert "ps -q worker" in check
    for fragment in ("docker inspect", ".Config.User", "10001:10001", "ReadonlyRootfs", "CapDrop", "no-new-privileges"):
        assert fragment in check, fragment
    # A worker that isn't isolated is stopped before the deploy fails, so it parses no more untrusted PDFs.
    failed = check[check.index("The worker is not isolated") :]
    assert failed.index('docker stop "$worker"') < failed.index("exit 1")
    assert "exec -T api python" in check
    assert "http://agent:8080/healthz" in check
    assert "http://mcp:8000/mcp" in check and "401" in check


ENSURE_HEALTHY = ON_PREMISE_DIR / "ensure-healthy.sh"
SCRIPTS = [
    DEPLOY_SCRIPT,
    ENSURE_HEALTHY,
    *(ON_PREMISE_DIR / name for name in ("backup.sh", "restore.sh", "report-failure.sh")),
]
SYSTEMD_DIR = ON_PREMISE_DIR / "systemd"


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script: Path) -> None:
    # On stdin: on Windows, `bash` may be WSL's, which can't open a Windows path.
    subprocess.run(["bash", "-n"], input=script.read_bytes(), check=True)


def test_files_the_vm_runs_keep_lf_line_endings() -> None:
    for path in (*SCRIPTS, ON_PREMISE_DIR / "compose.yaml", ON_PREMISE_DIR / "Caddyfile", *SYSTEMD_DIR.iterdir()):
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
    (eip_id,) = t.find_resources("AWS::EC2::EIP")

    assert config["Type"] == "HTTPS"
    assert config["Port"] == 443
    assert config["ResourcePath"] == "/api/healthz"
    # Through DNS, as a learner reaches it: a lapsed DuckDNS name fails the check too.
    assert config["FullyQualifiedDomainName"] == {
        "Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]
    }
    assert "IPAddress" not in config


def test_uptime_check_follows_the_domain_setting() -> None:
    t = host(**{"smart-tutor:on-premise-domain": "smart-tutor.duckdns.org"})
    (check,) = t.find_resources("AWS::Route53::HealthCheck").values()
    assert check["Properties"]["HealthCheckConfig"]["FullyQualifiedDomainName"] == "smart-tutor.duckdns.org"


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
    commands = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert " pull" not in commands and "migrate" not in commands


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
