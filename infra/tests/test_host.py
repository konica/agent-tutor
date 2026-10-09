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
    statements = [
        s for p in t.find_resources("AWS::IAM::Policy").values() for s in p["Properties"]["PolicyDocument"]["Statement"]
    ]
    return {s.get("Sid", json.dumps(s["Action"])): s for s in statements}


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
    (role,) = t.find_resources("AWS::IAM::Role").values()
    assert "AmazonSSMManagedInstanceCore" in json.dumps(role["Properties"]["ManagedPolicyArns"])
    statements = _statements(t)

    assert statements["EcrLogin"]["Resource"] == "*"
    pull = json.dumps(statements["EcrPullAppImages"]["Resource"])
    assert all(f"repository/smart-tutor/{s}" in pull for s in ("api", "web", "keycloak", "agent", "mcp", "worker"))
    assert "ecr:PutImage" not in json.dumps(statements)
    assert "parameter/smart-tutor-on-premise/*" in json.dumps(statements["ReadSettings"]["Resource"])
    assert "secret:smart-tutor-on-premise/*" in json.dumps(statements["ReadSecrets"]["Resource"])
    # Nothing of native-cloud's.
    assert "parameter/smart-tutor/" not in json.dumps(statements)
    assert "secret:smart-tutor/" not in json.dumps(statements)
    # Only the ECR login, which has no resource, may use "*".
    assert [sid for sid, s in statements.items() if s["Resource"] == "*"] == ["EcrLogin"]


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
    assert set(outputs) == {"InstanceId", "PublicIp", "PublicUrl", "DataVolumeId", "DeployDocumentName"}
    assert "Secret" not in json.dumps(outputs)


# --- files on the VM -----------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return yaml.safe_load((ON_PREMISE_DIR / "compose.yaml").read_text(encoding="utf-8"))


LONG_RUNNING = {"postgres", "keycloak", "api", "web", "caddy"}


def test_compose_runs_the_production_services_and_no_local_emulators(compose: dict[str, Any]) -> None:
    assert set(compose["services"]) == LONG_RUNNING | {"migrate"}
    assert compose["services"]["migrate"]["profiles"] == ["tools"]  # run by deploy.sh, never by `up`


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
    for name, repo in (("keycloak", "keycloak"), ("api", "api"), ("migrate", "api"), ("web", "web")):
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
    for path in ON_PREMISE_DIR.iterdir():
        assert not re.search(r"://[^\s/:@]+:[^\s/@]+@", path.read_text(encoding="utf-8")), path


def test_deploy_script_migrates_before_it_starts_the_new_tag() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert script.index("run --rm migrate") < script.index("up -d --wait --wait-timeout")


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_deploy_script_parses() -> None:
    # On stdin: on Windows, `bash` may be WSL's, which can't open a Windows path.
    subprocess.run(["bash", "-n"], input=DEPLOY_SCRIPT.read_bytes(), check=True)


def test_files_the_vm_runs_keep_lf_line_endings() -> None:
    for path in (DEPLOY_SCRIPT, ON_PREMISE_DIR / "compose.yaml", ON_PREMISE_DIR / "Caddyfile"):
        assert b"\r\n" not in path.read_bytes(), path
