"""The Langfuse-Host stack (spec 2026-10-14 §6, ADR 0021)."""

import json
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from langfuse_platform.app import build_app

CONTEXT = {
    "langfuse:region": "us-east-1",
    "langfuse:instance-type": "t3.xlarge",
    "langfuse:domain": "example-langfuse.duckdns.org",
    "langfuse:admin-email": "admin@example.com",
    "langfuse:data-snapshot-id": "",
}


def stack_template(**context: Any) -> Template:
    app = cdk.App(context={**CONTEXT, **context})
    return Template.from_stack(build_app(app))


@pytest.fixture(scope="module")
def t() -> Template:
    return stack_template()


def _statements(t: Template) -> dict[str, dict[str, Any]]:
    return {
        s["Sid"]: s
        for p in t.find_resources("AWS::IAM::Policy").values()
        for s in p["Properties"]["PolicyDocument"]["Statement"]
        if "Sid" in s
    }


def _parameter(t: Template, name: str) -> Any:
    (value,) = (
        p["Properties"]["Value"]
        for p in t.find_resources("AWS::SSM::Parameter").values()
        if p["Properties"]["Name"] == name
    )
    return value


def test_stack_is_named_for_langfuse_and_mentions_no_app(t: Template) -> None:
    text = json.dumps(t.to_json()).lower()
    assert "smart-tutor" not in text and "smarttutor" not in text and "smart_tutor" not in text


def test_own_vpc_with_one_public_subnet_and_only_http_and_https_in(t: Template) -> None:
    t.resource_count_is("AWS::EC2::VPC", 1)
    t.resource_count_is("AWS::EC2::Subnet", 1)
    t.resource_count_is("AWS::EC2::NatGateway", 0)
    t.has_resource_properties("AWS::EC2::VPC", {"CidrBlock": "10.42.0.0/16"})
    (group,) = t.find_resources("AWS::EC2::SecurityGroup").values()
    ingress = group["Properties"]["SecurityGroupIngress"]
    assert sorted((r["FromPort"], r["CidrIp"]) for r in ingress) == [(80, "0.0.0.0/0"), (443, "0.0.0.0/0")]


def test_instance_type_comes_from_context_with_imdsv2_and_no_ssh_key() -> None:
    t = stack_template(**{"langfuse:instance-type": "r7i.large"})
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    props = instance["Properties"]
    assert props["InstanceType"] == "r7i.large"
    assert "KeyName" not in props
    assert props["MetadataOptions"] == {"HttpTokens": "required", "HttpPutResponseHopLimit": 2}


def test_data_volume_is_100_gib_encrypted_and_snapshotted_daily_for_7_days(t: Template) -> None:
    t.has_resource_properties("AWS::EC2::Volume", {"Size": 100, "VolumeType": "gp3", "Encrypted": True})
    (policy,) = t.find_resources("AWS::DLM::LifecyclePolicy").values()
    (schedule,) = policy["Properties"]["PolicyDetails"]["Schedules"]
    assert schedule["CreateRule"]["Times"] == ["19:00"]  # 02:00 Asia/Ho_Chi_Minh
    assert schedule["RetainRule"] == {"Interval": 7, "IntervalUnit": "DAYS"}


def test_bucket_is_private_encrypted_tls_only_and_kept(t: Template) -> None:
    (bucket_id, bucket) = next(iter(t.find_resources("AWS::S3::Bucket").items()))
    props = bucket["Properties"]
    assert props["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "BlockPublicPolicy": True,
        "IgnorePublicAcls": True,
        "RestrictPublicBuckets": True,
    }
    assert props["BucketEncryption"]["ServerSideEncryptionConfiguration"][0]["ServerSideEncryptionByDefault"] == {
        "SSEAlgorithm": "AES256"
    }
    assert bucket["DeletionPolicy"] == "Retain"
    (policy,) = t.find_resources("AWS::S3::BucketPolicy").values()
    assert "aws:SecureTransport" in json.dumps(policy)
    (rule,) = props["CorsConfiguration"]["CorsRules"]
    assert sorted(rule["AllowedMethods"]) == ["GET", "PUT"]
    assert rule["AllowedOrigins"] == ["https://example-langfuse.duckdns.org"]


def test_instance_role_reads_only_its_own_settings_and_secrets_and_uses_its_bucket(t: Template) -> None:
    statements = _statements(t)
    assert "parameter/langfuse/host/*" in json.dumps(statements["ReadSettings"]["Resource"])
    assert "secret:langfuse/*" in json.dumps(statements["ReadSecrets"]["Resource"])
    every = json.dumps([p["Properties"] for p in t.find_resources("AWS::IAM::Policy").values()])
    assert "s3:PutObject" in every and "s3:DeleteObject" in every


def test_settings_for_deploy_sh(t: Template) -> None:
    assert _parameter(t, "/langfuse/host/domain") == "example-langfuse.duckdns.org"
    assert _parameter(t, "/langfuse/host/allow-signup") == "false"
    _parameter(t, "/langfuse/host/bundle")
    _parameter(t, "/langfuse/host/bucket")


def test_empty_domain_falls_back_to_the_elastic_ip_on_sslip_io() -> None:
    t = stack_template(**{"langfuse:domain": ""})
    (eip_id,) = t.find_resources("AWS::EC2::EIP")
    assert _parameter(t, "/langfuse/host/domain") == {
        "Fn::Join": ["", [{"Fn::GetAtt": [eip_id, "PublicIp"]}, ".sslip.io"]]
    }


def test_secrets_are_generated_under_langfuse(t: Template) -> None:
    names = sorted(s["Properties"]["Name"] for s in t.find_resources("AWS::SecretsManager::Secret").values())
    assert names == sorted(
        f"langfuse/{n}"
        for n in (
            "admin",
            "clickhouse",
            "db/postgres",
            "encryption-seed",
            "init-project-keys",
            "nextauth-secret",
            "salt",
            "valkey",
        )
    )
    (admin,) = (
        s["Properties"]
        for s in t.find_resources("AWS::SecretsManager::Secret").values()
        if s["Properties"]["Name"] == "langfuse/admin"
    )
    assert json.loads(admin["GenerateSecretString"]["SecretStringTemplate"]) == {"email": "admin@example.com"}
    assert admin["GenerateSecretString"]["GenerateStringKey"] == "password"


def test_deploy_document_takes_no_parameter_and_runs_the_bundled_script(t: Template) -> None:
    (document,) = t.find_resources("AWS::SSM::Document").values()
    props = document["Properties"]
    assert props["Name"] == "langfuse-deploy"
    assert "parameters" not in props["Content"]
    (step,) = props["Content"]["mainSteps"]
    commands = step["inputs"]["runCommand"]
    assert commands[-1] == "bash /opt/langfuse/deploy.sh"
    assert any(c.startswith("cloud-init status --wait") for c in commands)


def test_no_alarms(t: Template) -> None:
    t.resource_count_is("AWS::CloudWatch::Alarm", 0)
    t.resource_count_is("AWS::Route53::HealthCheck", 0)


def test_no_secret_reaches_the_template_or_the_user_data(t: Template) -> None:
    (instance,) = t.find_resources("AWS::EC2::Instance").values()
    user_data = json.dumps(instance["Properties"]["UserData"])
    assert "secretsmanager" not in user_data
    for secret in t.find_resources("AWS::SecretsManager::Secret").values():
        assert "SecretString" not in secret["Properties"]
