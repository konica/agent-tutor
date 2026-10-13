import json
import re

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from smart_tutor_infra.stacks.config import GUARD_MESSAGE, QUESTION_SCREEN_STRENGTH, ConfigStack


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
        "smart-tutor/phoenix/learner-hash-key",
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
    [key] = [s["Properties"] for s in secrets.values() if s["Properties"]["Name"].endswith("/phoenix/learner-hash-key")]
    assert key["Name"] == "smart-tutor-on-premise/phoenix/learner-hash-key"
    generated = key["GenerateSecretString"]
    assert generated["PasswordLength"] == 64 and generated["ExcludePunctuation"] is True
    assert "SecretStringTemplate" not in generated  # a plain string, read as the whole secret value


# --- the question screen's guardrail (#199) ------------------------------------------------------------------------


@pytest.mark.parametrize(("mode", "prefix"), [(NATIVE_CLOUD, "smart-tutor"), (ON_PREMISE, "smart-tutor-on-premise")])
def test_question_screen_guardrail_filters_prompt_attacks_in_the_question_only(mode: str, prefix: str) -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(mode)))

    (guardrail,) = template.find_resources("AWS::Bedrock::Guardrail").values()
    props = guardrail["Properties"]
    assert props["Name"] == f"{prefix}-question-screen"
    assert GUARD_MESSAGE == "I can only answer questions about your documents. Rephrase it to ask about their content."
    assert props["BlockedInputMessaging"] == props["BlockedOutputsMessaging"] == GUARD_MESSAGE
    assert QUESTION_SCREEN_STRENGTH == "LOW"  # measured 2026-10-13: 0 of 364 benign questions
    assert props["ContentPolicyConfig"]["FiltersConfig"] == [
        {
            "Type": "PROMPT_ATTACK",
            "InputStrength": QUESTION_SCREEN_STRENGTH,
            "OutputStrength": "NONE",
            "InputAction": "BLOCK",
            "InputEnabled": True,
            "OutputEnabled": False,
        }
    ]
    assert props["ContentPolicyConfig"]["ContentFiltersTierConfig"] == {"TierName": "STANDARD"}
    profile = props["CrossRegionConfig"]["GuardrailProfileArn"]["Fn::Join"][1]  # the parts of the ARN
    assert profile[-1].endswith("guardrail-profile/us.guardrail.v1:0")


def test_question_screen_version_is_retained_and_named_for_its_definition() -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(NATIVE_CLOUD)))

    (version,) = template.find_resources("AWS::Bedrock::GuardrailVersion").values()
    assert version["DeletionPolicy"] == "Retain" and version["UpdateReplacePolicy"] == "Retain"
    assert re.fullmatch(r"definition [0-9a-f]{12}", version["Properties"]["Description"])
    assert "QuestionScreen" in json.dumps(version["Properties"]["GuardrailIdentifier"])


@pytest.mark.parametrize(("mode", "path"), [(NATIVE_CLOUD, "/smart-tutor"), (ON_PREMISE, "/smart-tutor-on-premise")])
def test_question_screen_is_off_and_its_guardrail_is_in_ssm(mode: str, path: str) -> None:
    template = Template.from_stack(ConfigStack(cdk.App(), "Config", names=mode_names(mode)))

    template.has_resource_properties("AWS::SSM::Parameter", {"Name": f"{path}/question-guard", "Value": "off"})
    params = template.find_resources("AWS::SSM::Parameter").values()
    value = {p["Properties"]["Name"]: json.dumps(p["Properties"]["Value"]) for p in params}
    assert "QuestionScreen" in value[f"{path}/question-guardrail-id"]
    assert "QuestionScreenVersion" in value[f"{path}/question-guardrail-version"]
