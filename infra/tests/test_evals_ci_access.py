"""The CI evals role (#226, #337): the SmartTutor-EvalsCI stack, outside both deployment modes. Bedrock invoke on
exactly the models the evals call, trusted only for this repository's pull requests and branch runs."""

import json
from pathlib import Path

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Template

from smart_tutor_infra.app_stacks import build_app, build_evals_ci
from smart_tutor_infra.models import AGENT_MODEL, AGENT_MODEL_REGIONS, AGENT_PROFILE, EMBEDDING_MODEL, JUDGE_MODEL
from smart_tutor_infra.names import NATIVE_CLOUD, ON_PREMISE, mode_names
from smart_tutor_infra.stacks.evals_ci import ROLE_NAME, STACK_NAME
from tests.test_synth import CDK_CONTEXT

RUNBOOKS = Path(__file__).parents[2] / "docs/runbooks"
ACCOUNT = "123456789012"
PROVIDER = f"arn:aws:iam::{ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"


@pytest.fixture
def template(monkeypatch: pytest.MonkeyPatch) -> Template:
    monkeypatch.setenv("CDK_DEFAULT_ACCOUNT", ACCOUNT)  # the CDK CLI sets it from the caller's credentials
    return Template.from_stack(build_evals_ci(cdk.App(context=CDK_CONTEXT)))


def _role(template: Template) -> dict:
    (role,) = template.find_resources("AWS::IAM::Role").values()
    return role["Properties"]


def test_the_stack_and_role_have_their_fixed_names(template: Template) -> None:
    assert build_evals_ci(cdk.App(context=CDK_CONTEXT)).stack_name == STACK_NAME == "SmartTutor-EvalsCI"
    role = _role(template)
    assert role["RoleName"] == ROLE_NAME == "smart-tutor-evals-ci"
    assert role["MaxSessionDuration"] == 3600  # the workflow's 60-minute timeout
    # the one AWS::IAM::Policy (the default policy) is pinned below; no managed or inline policy may slip past it
    assert "ManagedPolicyArns" not in role and "Policies" not in role


def test_the_role_trusts_only_this_repositorys_pull_requests_and_branches(template: Template) -> None:
    (statement,) = _role(template)["AssumeRolePolicyDocument"]["Statement"]
    prefix = CDK_CONTEXT["smart-tutor:github-oidc-subject-prefix"]
    assert statement["Principal"] == {"Federated": PROVIDER}  # imported, never created
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Condition"]["StringEquals"] == {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
    assert sorted(statement["Condition"]["StringLike"]["token.actions.githubusercontent.com:sub"]) == sorted(
        [f"{prefix}:pull_request", f"{prefix}:ref:refs/heads/*"]
    )
    template.resource_count_is("AWS::IAM::OIDCProvider", 0)


def test_the_role_may_only_invoke_the_models_the_evals_call(template: Template) -> None:
    (policy,) = template.find_resources("AWS::IAM::Policy").values()
    (statement,) = policy["Properties"]["PolicyDocument"]["Statement"]
    assert statement["Sid"] == "InvokeEvalModels" and statement["Effect"] == "Allow"
    assert sorted(statement["Action"]) == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert sorted(statement["Resource"]) == sorted(
        [
            f"arn:aws:bedrock:us-east-1:{ACCOUNT}:inference-profile/{AGENT_PROFILE}",
            *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
            f"arn:aws:bedrock:us-east-1::foundation-model/{EMBEDDING_MODEL}",
            f"arn:aws:bedrock:us-east-1::foundation-model/{JUDGE_MODEL}",
        ]
    )


def test_the_stack_outputs_the_role_arn_for_the_github_secret(template: Template) -> None:
    assert "RoleArn" in template.find_outputs("*")


def test_a_given_provider_arn_is_imported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CDK_DEFAULT_ACCOUNT", ACCOUNT)
    other = "arn:aws:iam::999999999999:oidc-provider/token.actions.githubusercontent.com"
    app = cdk.App(context={**CDK_CONTEXT, "smart-tutor:github-oidc-provider-arn": other})
    (statement,) = _role(Template.from_stack(build_evals_ci(app)))["AssumeRolePolicyDocument"]["Statement"]
    assert statement["Principal"] == {"Federated": other}


def test_it_synthesizes_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CDK_DEFAULT_ACCOUNT", raising=False)
    Template.from_stack(build_evals_ci(cdk.App(context=CDK_CONTEXT))).resource_count_is("AWS::IAM::Role", 1)


@pytest.mark.parametrize("mode", [ON_PREMISE, NATIVE_CLOUD])
def test_no_deployment_mode_deploys_or_destroys_it(mode: str) -> None:
    # the deploy workflows run `cdk deploy --all -c smart-tutor:mode=<mode>`
    stacks = build_app(cdk.App(context={**CDK_CONTEXT, "smart-tutor:mode": mode}))
    assert STACK_NAME not in [s.stack_name for s in stacks]
    for stack in stacks:
        roles = Template.from_stack(stack).find_resources("AWS::IAM::Role").values()
        assert ROLE_NAME not in [r["Properties"].get("RoleName") for r in roles], stack.stack_name


def test_the_deploy_workflows_entry_does_not_build_it() -> None:
    # the workflows run `cdk deploy --all` against infra/app.py
    text = (Path(__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert "build_evals_ci" not in text and "EvalsCiStack" not in text


def test_it_names_no_resource_of_either_mode(template: Template) -> None:
    # not data_prefix itself (nor secret_prefix, which equals it): native-cloud's is plain "smart-tutor", a prefix of
    # this role's own name
    text = json.dumps(template.to_json())
    for mode in (ON_PREMISE, NATIVE_CLOUD):
        names = mode_names(mode, "prod")
        owned = (
            names.stack_prefix,
            names.resource_prefix,
            names.ingest_queue,
            names.ssm_path,
            f"{names.repository_prefix}/",
            names.deploy_role,
            names.deploy_document,
            names.documents_bucket(ACCOUNT),
        )
        for name in owned:
            assert name not in text, (mode, name)


def test_the_runbook_deploys_the_stack_and_names_the_secrets() -> None:
    text = (RUNBOOKS / "evals-ci.md").read_text(encoding="utf-8")
    for name in (
        "evals-smoke.yml",
        "SmartTutor-EvalsCI",
        "make evals-ci-deploy",
        "make evals-ci-destroy",
        "RoleArn",
        "smart-tutor-evals-ci",
        "EVALS_AWS_ROLE_ARN",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "smart-tutor-evals",
        "langfuse-host.md",
    ):
        assert name in text, name
    assert "aws iam create-role" not in text and "put-role-policy" not in text  # the stack makes the role
    assert not list(RUNBOOKS.glob("evals-ci-*.json"))  # one copy of the policy: the stack
