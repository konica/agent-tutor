import aws_cdk as cdk
from aws_cdk.assertions import Template

from smart_tutor_infra.stacks.config import ConfigStack


def test_file_limits_are_ssm_parameters() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-upload-mb", "Value": "50"})
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-pages", "Value": "500"})


def test_max_processing_attempts_is_an_ssm_parameter() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    template.has_resource_properties(
        "AWS::SSM::Parameter", {"Name": "/smart-tutor/max-processing-attempts", "Value": "3"}
    )


def test_keycloak_admin_and_client_secrets_are_generated_not_written() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config"))

    secrets = template.find_resources("AWS::SecretsManager::Secret")
    by_name = {s["Properties"]["Name"]: s["Properties"] for s in secrets.values()}
    assert set(by_name) == {
        "smart-tutor/keycloak/admin",
        "smart-tutor/keycloak/api-client",
        "smart-tutor/keycloak/mcp-client",
    }
    assert all("SecretString" not in p and "GenerateSecretString" in p for p in by_name.values())
    admin = by_name["smart-tutor/keycloak/admin"]["GenerateSecretString"]
    assert admin["SecretStringTemplate"] == '{"username": "admin"}'
    assert admin["GenerateStringKey"] == "password"
