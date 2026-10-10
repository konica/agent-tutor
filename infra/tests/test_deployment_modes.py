"""The CDK app builds one deployment mode, chosen by the context `smart-tutor:mode` (#147, PRD §9.12)."""

import json
from fnmatch import fnmatch
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from smart_tutor_infra.app_stacks import build_app
from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from tests.test_synth import CDK_CONTEXT, make_app, template

ON_PREMISE_STACKS = {f"SmartTutor-OnPremise-prod-{s}" for s in ("Storage", "Config", "Budgets", "GitHubDeploy", "Host")}
NATIVE_CLOUD_STACKS = {
    f"SmartTutor-prod-{s}"
    for s in ("Network", "Data", "Storage", "Cluster", "Registry", "Config", "Budgets", "GitHubDeploy", "Edge")
}


def on_premise(suffix: str) -> Template:
    return template(make_app(**{"smart-tutor:mode": ON_PREMISE}), suffix)


def test_on_premise_is_the_default_mode() -> None:
    app = cdk.App(context=CDK_CONTEXT)

    stacks = build_app(app)
    assembly = app.synth()

    assert {s.stack_name for s in stacks} == ON_PREMISE_STACKS
    assert {s.region for s in stacks} == {"us-east-1"}
    assert {s.stack_name for s in assembly.stacks} == ON_PREMISE_STACKS


def test_native_cloud_keeps_the_pilot_stack_names() -> None:
    app = make_app(**{"smart-tutor:mode": NATIVE_CLOUD})

    assert {s.stack_name for s in build_app(app)} == NATIVE_CLOUD_STACKS
    assert {s.stack_name for s in app.synth().stacks} == NATIVE_CLOUD_STACKS


def test_an_unknown_mode_fails_with_the_allowed_values() -> None:
    with pytest.raises(ValueError, match=r"'cloud'.*smart-tutor:mode.*on-premise, native-cloud"):
        build_app(make_app(**{"smart-tutor:mode": "cloud"}))


def test_on_premise_has_its_own_bucket_and_queues() -> None:
    t = on_premise("Storage")

    t.has_resource_properties(
        "AWS::S3::Bucket",
        {"BucketName": {"Fn::Join": ["", ["smart-tutor-on-premise-documents-", {"Ref": "AWS::AccountId"}]]}},
    )
    names = {q["Properties"]["QueueName"] for q in t.find_resources("AWS::SQS::Queue").values()}
    assert names == {"smart-tutor-on-premise-ingest", "smart-tutor-on-premise-ingest-dlq"}


def _cors_rules(**context: str) -> list[dict[str, Any]]:
    t = template(make_app(**{"smart-tutor:mode": ON_PREMISE, **context}), "Storage")
    bucket = next(iter(t.find_resources("AWS::S3::Bucket").values()))
    rules: list[dict[str, Any]] = bucket["Properties"]["CorsConfiguration"]["CorsRules"]
    return rules


def test_on_premise_bucket_cors_allows_sslip_io_to_post_uploads_and_get_documents() -> None:
    # GET is the document viewer's presigned link (#123); until #154 claims a name the host is <Elastic IP>.sslip.io.
    (rule,) = _cors_rules()

    assert rule["AllowedMethods"] == ["POST", "GET"]
    assert rule["ExposedHeaders"] == ["Accept-Ranges", "Content-Range", "Content-Length"]
    assert rule["AllowedHeaders"] == ["*"]
    assert rule["AllowedOrigins"] == ["https://*.sslip.io"]


def test_on_premise_storage_imports_nothing_from_the_host() -> None:
    # An import of the Elastic IP would block `cdk destroy` of the Host and the switch to a domain (#154).
    assert "Fn::ImportValue" not in json.dumps(on_premise("Storage").to_json())


def test_on_premise_bucket_cors_names_the_configured_domain() -> None:
    (rule,) = _cors_rules(**{"smart-tutor:on-premise-domain": "tutor.example.org"})

    assert rule["AllowedOrigins"] == ["https://tutor.example.org"]


def test_on_premise_has_its_own_parameters_and_secrets() -> None:
    t = on_premise("Config")

    params = {p["Properties"]["Name"] for p in t.find_resources("AWS::SSM::Parameter").values()}
    secrets = {s["Properties"]["Name"] for s in t.find_resources("AWS::SecretsManager::Secret").values()}
    assert params and all(p.startswith("/smart-tutor-on-premise/") for p in params)
    assert secrets == {
        "smart-tutor-on-premise/keycloak/admin",
        "smart-tutor-on-premise/keycloak/api-client",
        "smart-tutor-on-premise/keycloak/mcp-client",
    }


def test_on_premise_has_its_own_budget() -> None:
    on_premise("Budgets").has_resource_properties(
        "AWS::Budgets::Budget", {"Budget": Match.object_like({"BudgetName": "smart-tutor-on-premise-prod-monthly"})}
    )


def test_on_premise_deploy_role_trusts_its_own_environment_and_reads_only_its_stacks() -> None:
    t = on_premise("GitHubDeploy")

    # The account's GitHub provider is native-cloud's; one URL has one provider per account.
    t.resource_count_is("AWS::IAM::OIDCProvider", 0)
    t.has_resource_properties(
        "AWS::IAM::Role",
        {
            "RoleName": "smart-tutor-on-premise-github-deploy",
            "AssumeRolePolicyDocument": {
                "Statement": [
                    Match.object_like(
                        {
                            "Condition": {
                                "StringEquals": Match.object_like(
                                    {
                                        "token.actions.githubusercontent.com:sub": (
                                            "repo:konica@1114311/agent-tutor@1399048529:environment:on-premise"
                                        )
                                    }
                                )
                            }
                        }
                    )
                ]
            },
        },
    )
    statements = next(iter(t.find_resources("AWS::IAM::Policy").values()))["Properties"]["PolicyDocument"]["Statement"]
    assert [s["Sid"] for s in statements] == ["AssumeCdkBootstrapRoles", "EcrLogin", "EcrPushAppImages", "ReadStackOutputs"]
    (outputs,) = (s for s in statements if s["Sid"] == "ReadStackOutputs")
    assert "stack/SmartTutor-OnPremise-prod-*/*" in str(outputs["Resource"])


def test_on_premise_references_the_shared_registry_instead_of_creating_one() -> None:
    app = make_app(**{"smart-tutor:mode": ON_PREMISE})

    for stack in build_app(app):
        Template.from_stack(stack).resource_count_is("AWS::ECR::Repository", 0)


def test_native_cloud_access_patterns_match_none_of_on_premise_names() -> None:
    native, onprem = mode_names(NATIVE_CLOUD), mode_names(ON_PREMISE)

    # The globs native-cloud's IAM grants on (ClusterStack, GitHubDeployStack).
    assert not fnmatch(f"{onprem.ssm_path}/max-pages", f"{native.ssm_path}/*")
    assert not fnmatch(f"{onprem.secret_prefix}/keycloak/admin", f"{native.secret_prefix}/*")
    assert not fnmatch(f"{onprem.stack_prefix}-Storage", f"{native.stack_prefix}-*")
    assert onprem.documents_bucket("1") != native.documents_bucket("1")
    assert onprem.ingest_queue != native.ingest_queue
    assert onprem.deploy_role != native.deploy_role


def test_on_premise_budget_alerts_the_same_recipients_as_native_cloud() -> None:
    def subscribers(t: Template) -> list[object]:
        (budget,) = t.find_resources("AWS::Budgets::Budget").values()
        return [n["Subscribers"] for n in budget["Properties"]["NotificationsWithSubscribers"]]

    native = subscribers(template(make_app(), "Budgets"))
    assert native and subscribers(on_premise("Budgets")) == native
