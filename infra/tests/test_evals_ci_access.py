"""The CI evals role (#226): Bedrock invoke on exactly the models the evals call, trusted only for this repository's
pull requests and branch runs."""

import json
from pathlib import Path

from smart_tutor_infra.models import (
    AGENT_MODEL,
    AGENT_MODEL_REGIONS,
    AGENT_PROFILE,
    EMBEDDING_MODEL,
    JUDGE_MODEL,
)
from tests.test_synth import CDK_CONTEXT

RUNBOOKS = Path(__file__).parents[2] / "docs/runbooks"


def policy(name: str) -> dict:
    return json.loads((RUNBOOKS / name).read_text(encoding="utf-8"))


def test_the_role_may_only_invoke_the_models_the_evals_call() -> None:
    (statement,) = policy("evals-ci-bedrock-policy.json")["Statement"]
    assert statement["Effect"] == "Allow"
    assert sorted(statement["Action"]) == [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
    ]
    assert sorted(statement["Resource"]) == sorted(
        [
            f"arn:aws:bedrock:us-east-1:ACCOUNT_ID:inference-profile/{AGENT_PROFILE}",
            *(
                f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}"
                for r in AGENT_MODEL_REGIONS
            ),
            f"arn:aws:bedrock:us-east-1::foundation-model/{EMBEDDING_MODEL}",
            f"arn:aws:bedrock:us-east-1::foundation-model/{JUDGE_MODEL}",
        ]
    )


def test_the_role_trusts_only_this_repositorys_pull_requests_and_branches() -> None:
    (statement,) = policy("evals-ci-trust-policy.json")["Statement"]
    prefix = CDK_CONTEXT["smart-tutor:github-oidc-subject-prefix"]
    assert statement["Principal"] == {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    }
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Condition"]["StringEquals"] == {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
    }
    assert sorted(
        statement["Condition"]["StringLike"]["token.actions.githubusercontent.com:sub"]
    ) == sorted([f"{prefix}:pull_request", f"{prefix}:ref:refs/heads/*"])


def test_the_runbook_names_the_workflow_the_variable_and_the_secrets() -> None:
    text = (RUNBOOKS / "evals-ci.md").read_text(encoding="utf-8")
    for name in (
        "evals-smoke.yml",
        "EVALS_AWS_ROLE_ARN",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_BASE_URL",
        "smart-tutor-evals",
        "langfuse-host.md",
        "evals-ci-bedrock-policy.json",
        "evals-ci-trust-policy.json",
        "smart-tutor-evals-ci",
    ):
        assert name in text, name
