import aws_cdk as cdk
from aws_cdk.assertions import Template

from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from smart_tutor_infra.stacks.config import ConfigStack


def test_file_limits_are_ssm_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-upload-mb", "Value": "50"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-pages", "Value": "500"})


def test_max_processing_attempts_is_an_ssm_parameter() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/smart-tutor/max-processing-attempts", "Value": "3"}
    )


def test_upload_rate_limits_are_ssm_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/smart-tutor/max-uploads-per-hour", "Value": "20"}
    )
    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/smart-tutor/max-uploads-per-day", "Value": "100"}
    )


def test_no_subject_detection_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    names = {p["Properties"]["Name"] for p in template.find_resources("AWS::SSM::Parameter").values()}
    assert not names & {"/smart-tutor/detect-threshold", "/smart-tutor/detect-margin", "/smart-tutor/multi-margin"}


def test_app_time_zone_is_an_ssm_parameter() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/smart-tutor/app-time-zone", "Value": "Asia/Ho_Chi_Minh"}
    )


def test_secrets_are_generated_not_written() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    secrets = template.find_resources("AWS::SecretsManager::Secret")
    by_name = {s["Properties"]["Name"]: s["Properties"] for s in secrets.values()}
    assert set(by_name) == {
        "smart-tutor/keycloak/admin",
        "smart-tutor/keycloak/api-client",
        "smart-tutor/keycloak/mcp-client",
        "smart-tutor/langsmith/learner-hash-key",
    }
    assert all("SecretString" not in p and "GenerateSecretString" in p for p in by_name.values())
    admin = by_name["smart-tutor/keycloak/admin"]["GenerateSecretString"]
    assert admin["SecretStringTemplate"] == '{"username": "admin"}'
    assert admin["GenerateStringKey"] == "password"


def test_trace_sampling_rate_is_an_ssm_parameter_tracing_every_run() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/trace-sampling-rate", "Value": "1"})


def test_learner_hash_key_is_a_long_generated_string_per_mode() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(ON_PREMISE)))

    secrets = template.find_resources("AWS::SecretsManager::Secret")
    [key] = [s["Properties"] for s in secrets.values() if s["Properties"]["Name"].endswith("/langsmith/learner-hash-key")]
    assert key["Name"] == "smart-tutor-on-premise/langsmith/learner-hash-key"
    generated = key["GenerateSecretString"]
    assert generated["PasswordLength"] == 64 and generated["ExcludePunctuation"] is True
    assert "SecretStringTemplate" not in generated  # a plain string, read as the whole secret value
