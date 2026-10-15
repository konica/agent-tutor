"""The CDK app builds one deployment mode, chosen by the context `smart-tutor:mode` (#147, PRD §9.12)."""

import json
import re
from fnmatch import fnmatch
from typing import Any

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

from smart_tutor_infra.app_stacks import build_app
from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from tests.test_synth import CDK_CONTEXT, make_app, template

ON_PREMISE_STACKS = {
    f"SmartTutor-OnPremise-prod-{s}" for s in ("Storage", "Config", "Budgets", "GitHubDeploy", "Registry", "Host")
}
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


def test_on_premise_bucket_cors_allows_the_duckdns_name_to_post_uploads_and_get_documents() -> None:
    # GET is the document viewer's presigned link (#123); the host is the DuckDNS name in cdk.json (#154).
    (rule,) = _cors_rules()

    assert rule["AllowedMethods"] == ["POST", "GET"]
    assert rule["ExposedHeaders"] == ["Accept-Ranges", "Content-Range", "Content-Length"]
    assert rule["AllowedHeaders"] == ["*"]
    assert rule["AllowedOrigins"] == ["https://smart-tutor.duckdns.org"]


def test_on_premise_bucket_cors_allows_sslip_io_without_a_domain() -> None:
    # Without a domain the host is <Elastic IP>.sslip.io, which Storage names without referencing the Host.
    (rule,) = _cors_rules(**{"smart-tutor:on-premise-domain": ""})

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
        "smart-tutor-on-premise/phoenix/learner-hash-key",
        "smart-tutor-on-premise/langfuse/learner-hash-key",
    }
    # The shared Langfuse host's address (ADR 0023), from cdk.json.
    values = {
        p["Properties"]["Name"]: p["Properties"]["Value"] for p in t.find_resources("AWS::SSM::Parameter").values()
    }
    assert values["/smart-tutor-on-premise/langfuse-url"] == "https://sec-dog.duckdns.org"


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
    assert [s["Sid"] for s in statements] == [
        "AssumeCdkBootstrapRoles",
        "EcrLogin",
        "EcrPushAppImages",
        "RunDeployDocument",
        "ReadDeployStatus",
        "ReadStackOutputs",
    ]
    assert not [s for s in statements if "ssm:GetParameter" in str(s["Action"])]
    (outputs,) = (s for s in statements if s["Sid"] == "ReadStackOutputs")
    assert "stack/SmartTutor-OnPremise-prod-*/*" in str(outputs["Resource"])


def test_on_premise_deploy_role_runs_only_the_deploy_document() -> None:
    statements = {
        s["Sid"]: s
        for s in next(iter(on_premise("GitHubDeploy").find_resources("AWS::IAM::Policy").values()))["Properties"][
            "PolicyDocument"
        ]["Statement"]
    }
    run = statements["RunDeployDocument"]
    assert run["Action"] == "ssm:SendCommand"
    resources = json.dumps(run["Resource"])
    # SendCommand is authorized on the document and on the instance; the only document is the deploy one.
    assert ":document/smart-tutor-on-premise-deploy" in resources
    assert ":instance/*" in resources
    assert "AWS-RunShellScript" not in resources and ":document/*" not in resources
    status = statements["ReadDeployStatus"]
    # Neither action supports resource-level permissions.
    assert sorted(status["Action"]) == ["ssm:DescribeInstanceInformation", "ssm:GetCommandInvocation"]
    assert status["Resource"] == "*"


def test_deploy_document_name_comes_from_mode_names() -> None:
    assert mode_names(ON_PREMISE).deploy_document == "smart-tutor-on-premise-deploy"
    on_premise("Host").has_resource_properties("AWS::SSM::Document", {"Name": "smart-tutor-on-premise-deploy"})


def test_each_mode_names_its_repositories_after_its_data_prefix() -> None:
    assert mode_names(ON_PREMISE).repository("api") == "smart-tutor-on-premise/api"
    assert mode_names(NATIVE_CLOUD).repository("api") == "smart-tutor/api"  # the names the pilot was deployed with
    # The globs each deploy role pushes to (GitHubDeployStack) don't overlap.
    native, onprem = mode_names(NATIVE_CLOUD), mode_names(ON_PREMISE)
    assert not fnmatch(onprem.repository("api"), f"{native.repository_prefix}/*")
    assert not fnmatch(native.repository("api"), f"{onprem.repository_prefix}/*")


def test_on_premise_has_a_registry_of_its_own() -> None:
    t = on_premise("Registry")

    repos = t.find_resources("AWS::ECR::Repository")
    names = sorted(r["Properties"]["RepositoryName"] for r in repos.values())
    assert names == [f"smart-tutor-on-premise/{s}" for s in ["agent", "api", "keycloak", "mcp", "web", "worker"]]
    for repo in repos.values():
        assert repo["Properties"]["ImageScanningConfiguration"] == {"ScanOnPush": True}
        assert repo["Properties"]["EmptyOnDelete"] is True
        assert repo["DeletionPolicy"] == "Delete"
        assert '"countNumber":30' in repo["Properties"]["LifecyclePolicy"]["LifecyclePolicyText"]
    t.has_output("RegistryUri", {})


def test_no_on_premise_template_names_a_native_cloud_repository() -> None:
    app = make_app(**{"smart-tutor:mode": ON_PREMISE})

    for stack in build_app(app):
        rendered = json.dumps(Template.from_stack(stack).to_json())
        assert not re.search(r"smart-tutor/(api|web|keycloak|agent|mcp|worker)\b", rendered), stack.stack_name


def test_on_premise_deploy_role_pushes_only_to_its_own_repositories() -> None:
    (policy,) = on_premise("GitHubDeploy").find_resources("AWS::IAM::Policy").values()
    push = next(s for s in policy["Properties"]["PolicyDocument"]["Statement"] if s["Sid"] == "EcrPushAppImages")
    resource = json.dumps(push["Resource"])
    assert ":repository/smart-tutor-on-premise/*" in resource
    assert ":repository/smart-tutor/*" not in resource


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


# EC2 accepts only these characters in a security group or rule description, and rejects others only at deploy time.
EC2_DESCRIPTION = re.compile(r"[a-zA-Z0-9 ._\-:/()#,@\[\]+=&;{}!$*]{0,255}")


def _security_group_descriptions(resource: dict[str, Any]) -> list[Any]:
    properties = resource.get("Properties", {})
    if resource["Type"] == "AWS::EC2::SecurityGroup":
        rules = properties.get("SecurityGroupIngress", []) + properties.get("SecurityGroupEgress", [])
        return [properties.get("GroupDescription")] + [rule.get("Description") for rule in rules]
    if resource["Type"] in ("AWS::EC2::SecurityGroupIngress", "AWS::EC2::SecurityGroupEgress"):
        return [properties.get("Description")]
    return []


@pytest.mark.parametrize("mode", [ON_PREMISE, NATIVE_CLOUD])
def test_security_group_and_rule_descriptions_use_only_characters_ec2_accepts(mode: str) -> None:
    descriptions = [
        description
        for stack in build_app(make_app(**{"smart-tutor:mode": mode}))
        for resource in Template.from_stack(stack).to_json().get("Resources", {}).values()
        for description in _security_group_descriptions(resource)
        if isinstance(description, str)
    ]

    assert descriptions
    assert [d for d in descriptions if not EC2_DESCRIPTION.fullmatch(d)] == []
