# CI evals role as a CDK stack — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The GitHub Actions role for the smoke evals, `smart-tutor-evals-ci`, is created and removed by a CDK stack, `SmartTutor-EvalsCI`, instead of hand-run `aws iam` commands and checked-in policy JSON (issue #337).

**Architecture:** A new stack class `EvalsCiStack` in `infra/smart_tutor_infra/stacks/evals_ci.py` holds the role and its Bedrock-invoke policy, built from the model ids in `smart_tutor_infra/models.py`. It belongs to neither deployment mode. A builder `build_evals_ci(app)` in `app_stacks.py` and its own CDK entry `infra/evals_ci_app.py` keep it out of `build_app`, so the deploy workflows' `cdk deploy --all -c smart-tutor:mode=…` never deploys or destroys it. An admin deploys it once with `make evals-ci-deploy` and removes it with `make evals-ci-destroy`. It imports the account's GitHub OIDC provider by ARN, the one shared resource ADR 0016 allows.

**Tech Stack:** AWS CDK v2 (Python, `aws-cdk-lib`), pytest with `aws_cdk.assertions.Template`, uv; CDK CLI `npx --yes aws-cdk@2.1145.0` (the version the deploy workflows pin).

**Spec:** Issue #337 (parent #220; the role was first specified in #226, `sdd/plans/2026-10-11-smoke-evals-ci.md`). ADR 0016 (`sdd/adr/0016-deployment-modes-share-no-stack.md`).

## Global Constraints

- Stack name `SmartTutor-EvalsCI`; role name `smart-tutor-evals-ci`; max session 1 hour (the workflow's `timeout-minutes: 60`).
- Trust: federated principal = the account's GitHub OIDC provider `arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com` (context `smart-tutor:github-oidc-provider-arn` overrides it, as for on-premise's GitHubDeploy), action `sts:AssumeRoleWithWebIdentity`, `StringEquals` `token.actions.githubusercontent.com:aud` = `sts.amazonaws.com`, `StringLike` `token.actions.githubusercontent.com:sub` = `[<prefix>:pull_request, <prefix>:ref:refs/heads/*]`, prefix from context `smart-tutor:github-oidc-subject-prefix` (`infra/cdk.json`).
- Permissions: exactly one statement, Sid `InvokeEvalModels`, actions `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream`, resources: `arn:aws:bedrock:<region>:<account>:inference-profile/<AGENT_PROFILE>`, `arn:aws:bedrock:<r>::foundation-model/<AGENT_MODEL>` for each `r` in `AGENT_MODEL_REGIONS`, `arn:aws:bedrock:<region>::foundation-model/<EMBEDDING_MODEL>`, `arn:aws:bedrock:<region>::foundation-model/<JUDGE_MODEL>` (`<region>` = the stack's region, context `smart-tutor:region`, `us-east-1`). Nothing else: no S3, SSM, ECR, or deploy rights.
- The stack outputs the role's ARN as output `RoleArn`.
- The account comes from `CDK_DEFAULT_ACCOUNT` (the CDK CLI sets it from the caller's credentials).
- No change to `build_app` or either deployment mode's stacks; `infra/tests/test_mode_isolation.py` and `test_deployment_modes.py` must still pass.
- Infra check: `cd infra && uv run pytest`.
- Commit subjects in the imperative mood, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Synth without AWS credentials (no `CDK_DEFAULT_ACCOUNT`, e.g. a unit test or `cdk synth` offline): the stack still synthesizes, with the account as a token. (Task 1 test.)
- A deploy workflow's `cdk deploy --all -c smart-tutor:mode=on-premise` or `native-cloud`: it must not list `SmartTutor-EvalsCI` or any role named `smart-tutor-evals-ci`. (Task 1 test.)
- A model id changes in `models.py`: the role's policy changes with it on the next `make evals-ci-deploy`; no second copy of the ids can drift. (Task 1 test derives expectations from `models.py`; Task 2 deletes the JSON.)
- The stack names no resource of either mode (stack prefixes, data prefixes, deploy roles), so tearing down a mode can't reach it and it can't reach a mode. (Task 1 test.)
- An admin following the runbook after a model change, or removing the evals: the runbook gives the exact commands, and the old `aws iam create-role` steps are gone. (Task 2 test.)

---

### Task 1: The `SmartTutor-EvalsCI` stack, its entry, and the Make targets

**Files:**
- Create: `infra/smart_tutor_infra/stacks/evals_ci.py`
- Create: `infra/evals_ci_app.py`
- Modify: `infra/smart_tutor_infra/app_stacks.py` (add `build_evals_ci`; `build_app` unchanged)
- Modify: `Makefile` (targets `evals-ci-deploy`, `evals-ci-destroy`, and `.PHONY`)
- Modify: `infra/smart_tutor_infra/models.py` (module docstring: the role is the `SmartTutor-EvalsCI` stack, not the runbook)
- Test: `infra/tests/test_evals_ci_access.py` (replace the JSON tests with template tests; keep the runbook test until Task 2 rewrites it)

**Interfaces:**
- Produces: `class EvalsCiStack(cdk.Stack)` with `__init__(self, scope, construct_id, *, subject_prefix: str, provider_arn: str | None = None, **kwargs)` and attribute `role: iam.Role`; constants `STACK_NAME = "SmartTutor-EvalsCI"`, `ROLE_NAME = "smart-tutor-evals-ci"` in `evals_ci.py`; `def build_evals_ci(app: cdk.App) -> EvalsCiStack` in `app_stacks.py`.

- [ ] **Step 1: Write the failing tests.** Replace the two policy-JSON tests in `infra/tests/test_evals_ci_access.py` (keep `test_the_runbook_names_the_workflow_the_variable_and_the_secrets` as is for now) with:

```python
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


def test_it_names_no_resource_of_either_mode(template: Template) -> None:
    # not data_prefix itself: native-cloud's is plain "smart-tutor", a prefix of this role's own name
    text = json.dumps(template.to_json())
    for mode in (ON_PREMISE, NATIVE_CLOUD):
        names = mode_names(mode, "prod")
        owned = (
            names.stack_prefix,
            names.resource_prefix,
            names.ingest_queue,
            names.ssm_path,
            names.secret_prefix,
            f"{names.repository_prefix}/",
            names.deploy_role,
            names.deploy_document,
            names.documents_bucket(ACCOUNT),
        )
        for name in owned:
            assert name not in text, (mode, name)
```

- [ ] **Step 2: Run the tests to verify they fail.**
Run: `cd infra && uv run pytest tests/test_evals_ci_access.py -q`
Expected: collection error `ImportError: cannot import name 'build_evals_ci'`.

- [ ] **Step 3: Write the stack** `infra/smart_tutor_infra/stacks/evals_ci.py`:

```python
"""GitHub Actions access for the smoke evals (#226, #337): the role `evals-smoke.yml` signs in with.

It belongs to neither deployment mode (ADR 0024): `build_app` never builds it, so a mode's `cdk deploy --all` or
teardown can't touch it. An admin deploys it from a laptop (`make evals-ci-deploy`), because GitHub Actions can't
create the role it signs in with, and removes it with `make evals-ci-destroy`. It imports the account's GitHub OIDC
provider by ARN, the one resource ADR 0016 lets stacks share.
"""

from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from constructs import Construct

from smart_tutor_infra.models import AGENT_MODEL, AGENT_MODEL_REGIONS, AGENT_PROFILE, EMBEDDING_MODEL, JUDGE_MODEL
from smart_tutor_infra.stacks.github_deploy import GITHUB_OIDC_HOST

STACK_NAME = "SmartTutor-EvalsCI"
ROLE_NAME = "smart-tutor-evals-ci"


class EvalsCiStack(cdk.Stack):
    """The role trusts this repository's pull requests and branch runs (any workflow on any branch, written by anyone
    with push access), so it may do nothing but invoke the models the evals call: the agent model, the embeddings,
    and the judge. That is the bound on its trust; the cost is Bedrock spend."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        subject_prefix: str,
        provider_arn: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        provider = iam.OidcProviderNative.from_oidc_provider_arn(
            self, "GitHubOidc", provider_arn or f"arn:aws:iam::{self.account}:oidc-provider/{GITHUB_OIDC_HOST}"
        )
        self.role = iam.Role(
            self,
            "EvalsRole",
            role_name=ROLE_NAME,
            description="GitHub Actions smoke evals: Bedrock invoke only (#226, #337)",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {f"{GITHUB_OIDC_HOST}:aud": "sts.amazonaws.com"},
                    "StringLike": {
                        f"{GITHUB_OIDC_HOST}:sub": [
                            f"{subject_prefix}:pull_request",
                            f"{subject_prefix}:ref:refs/heads/*",
                        ]
                    },
                },
            ),
        )
        region = self.region
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="InvokeEvalModels",
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    f"arn:aws:bedrock:{region}:{self.account}:inference-profile/{AGENT_PROFILE}",
                    *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
                    f"arn:aws:bedrock:{region}::foundation-model/{EMBEDDING_MODEL}",
                    f"arn:aws:bedrock:{region}::foundation-model/{JUDGE_MODEL}",
                ],
            )
        )
        cdk.CfnOutput(self, "RoleArn", value=self.role.role_arn, description="gh secret set EVALS_AWS_ROLE_ARN")
```

- [ ] **Step 4: Add the builder** to `infra/smart_tutor_infra/app_stacks.py` (import `os` and `EvalsCiStack, STACK_NAME` from `smart_tutor_infra.stacks.evals_ci`; append after `build_app`'s helpers):

```python
def build_evals_ci(app: cdk.App) -> EvalsCiStack:
    """The CI evals role's stack (#337). Not part of any mode: only `evals_ci_app.py` builds it, never `build_app`."""
    env = cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=app.node.try_get_context("smart-tutor:region") or "us-east-1",
    )
    return EvalsCiStack(
        app,
        STACK_NAME,
        env=env,
        subject_prefix=app.node.get_context("smart-tutor:github-oidc-subject-prefix"),
        provider_arn=app.node.try_get_context("smart-tutor:github-oidc-provider-arn"),
    )
```

and the entry `infra/evals_ci_app.py`:

```python
"""CDK entry for the CI evals role (#337), apart from the deployment modes' `app.py`:
`npx --yes aws-cdk@2.1145.0 deploy --app "uv run python evals_ci_app.py" SmartTutor-EvalsCI` (make evals-ci-deploy).
It reads the same context from cdk.json."""

import aws_cdk as cdk

from smart_tutor_infra.app_stacks import build_evals_ci

app = cdk.App()
build_evals_ci(app)
app.synth()
```

- [ ] **Step 5: Add the Make targets** after `infra-synth` in `Makefile`, and add `evals-ci-deploy evals-ci-destroy` to `.PHONY`:

```make
# The CI evals role (#337): its own CDK app, outside both modes. Run with an admin profile and real AWS (no LocalStack
# endpoints in the shell), once, and again after a model change in infra/smart_tutor_infra/models.py.
EVALS_CI_CDK := cd infra && npx --yes aws-cdk@2.1145.0 --app "uv run python evals_ci_app.py"
evals-ci-deploy: ## deploy SmartTutor-EvalsCI, the GitHub Actions role for the smoke evals (docs/runbooks/evals-ci.md)
	$(EVALS_CI_CDK) deploy SmartTutor-EvalsCI --require-approval broadening
evals-ci-destroy: ## remove SmartTutor-EvalsCI and its role
	$(EVALS_CI_CDK) destroy SmartTutor-EvalsCI
```

Update the `models.py` docstring's last paragraph to: `The CI evals role (stack SmartTutor-EvalsCI, stacks/evals_ci.py, #226, #337) is granted the same models plus the eval judge, JUDGE_MODEL.`

- [ ] **Step 6: Run the tests to verify they pass.**
Run: `cd infra && uv run pytest tests/test_evals_ci_access.py -q`
Expected: all pass except possibly `test_the_runbook_names_…`, which still passes (the runbook is unchanged until Task 2).
Then: `cd infra && uv run pytest -q` — expected: all pass (mode isolation and synth tests unchanged).
Then: `cd infra && CDK_DEFAULT_ACCOUNT=123456789012 uv run python evals_ci_app.py` — expected: exits 0 and writes `cdk.out/SmartTutor-EvalsCI.template.json`.

- [ ] **Step 7: Commit**

```bash
git add infra/smart_tutor_infra/stacks/evals_ci.py infra/evals_ci_app.py infra/smart_tutor_infra/app_stacks.py infra/smart_tutor_infra/models.py infra/tests/test_evals_ci_access.py Makefile
git commit -m "Create the CI evals role with a CDK stack outside both modes (#337)"
```

---

### Task 2: Runbook, ADR, and removing the policy JSON

**Files:**
- Delete: `docs/runbooks/evals-ci-bedrock-policy.json`, `docs/runbooks/evals-ci-trust-policy.json`
- Modify: `docs/runbooks/evals-ci.md` (sections "Why a separate role", "Create it", "When a model changes"; add "Remove it")
- Create: `sdd/adr/0024-ci-evals-role-is-its-own-stack.md`
- Modify: `sdd/adr/README.md` (index row 0024), `AGENTS.md` (`sdd/adr/` (0001–0023) → (0001–0024))
- Test: `infra/tests/test_evals_ci_access.py` (rewrite the runbook test)

**Interfaces:**
- Consumes: from Task 1, `make evals-ci-deploy`, `make evals-ci-destroy`, stack `SmartTutor-EvalsCI`, output `RoleArn`, role `smart-tutor-evals-ci`.

- [ ] **Step 1: Write the failing test.** Replace `test_the_runbook_names_the_workflow_the_variable_and_the_secrets` with:

```python
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
```

- [ ] **Step 2: Run it to verify it fails.**
Run: `cd infra && uv run pytest tests/test_evals_ci_access.py::test_the_runbook_deploys_the_stack_and_names_the_secrets -q`
Expected: FAIL on `SmartTutor-EvalsCI`.

- [ ] **Step 3: Rewrite the runbook sections.** In `docs/runbooks/evals-ci.md`:
  - Intro: "A maintainer creates the role, the secrets, and the variable once" → "A maintainer deploys the role's stack and sets the secrets and the variable once".
  - The table row for `EVALS_AWS_ROLE_ARN`: "The Bedrock-only role below (output `RoleArn` of `SmartTutor-EvalsCI`)".
  - "Why a separate role": keep the reasoning; replace its last paragraph (about `test_evals_ci_access.py` keeping two JSON files in step) with: "The role is the stack `SmartTutor-EvalsCI` (`infra/smart_tutor_infra/stacks/evals_ci.py`). It belongs to neither deployment mode (ADR 0024): the deploy workflows' `cdk deploy --all` never touches it, and a mode's teardown leaves it. Its policy is built from `infra/smart_tutor_infra/models.py`, the same model ids the deployments use, so there is no second copy to keep in step."
  - Replace "## Create it" (the OIDC-provider note can stay, the `ACCOUNT_ID`/`sed`/`aws iam create-role`/`put-role-policy` block goes) with:

    ````markdown
    ## Deploy the role

    Run once, with your admin profile and real AWS (see `on-premise-deploy.md` §1 for the shell setup: no LocalStack endpoints). It assumes the account's GitHub OIDC provider exists; native-cloud's `GitHubDeploy` stack creates it (ADR 0016). If `aws iam list-open-id-connect-providers` shows no `token.actions.githubusercontent.com`, create it first:

    ```bash
    aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
    ```

    Then, from the repository root (no `make`? run the two lines of the `evals-ci-deploy` target in the `Makefile` by hand):

    ```bash
    make evals-ci-deploy
    ROLE_ARN=$(aws cloudformation describe-stacks --stack-name SmartTutor-EvalsCI --query "Stacks[0].Outputs[?OutputKey=='RoleArn'].OutputValue" --output text)
    gh secret set EVALS_AWS_ROLE_ARN --repo konica/agent-tutor --body "$ROLE_ARN"
    ```

    The stack makes one role, `smart-tutor-evals-ci`, and its inline Bedrock policy; CDK shows the IAM changes and asks before deploying them. GitHub Actions can't deploy it: no workflow may create the role it signs in with.

    ## Remove it

    ```bash
    make evals-ci-destroy
    gh secret delete EVALS_AWS_ROLE_ARN --repo konica/agent-tutor
    ```

    The smoke job then skips with a warning until the stack and the secret exist again. The OIDC provider stays: it isn't this stack's.
    ````

    On Windows Git Bash keep the existing `MSYS_NO_PATHCONV=1` note.
  - "## When a model changes": "Change the model in `backend/src/smart_tutor/shared/config.py` and `infra/smart_tutor_infra/models.py`, then run `make evals-ci-deploy` again: the role's policy follows `models.py`."
  - Keep the Langfuse, night, forks, and cost sections unchanged.

- [ ] **Step 4: Delete the JSON files.**
Run: `git rm docs/runbooks/evals-ci-bedrock-policy.json docs/runbooks/evals-ci-trust-policy.json`

- [ ] **Step 5: Write ADR 0024** `sdd/adr/0024-ci-evals-role-is-its-own-stack.md`, in the format of `0016` (Status accepted, Date 2026-10-15; Context, Decision, Alternatives rejected, Consequences):
  - Context: #226 created the role by hand from checked-in JSON; the PO (2026-10-15, #337) wants every AWS resource in a stack so it can be tracked and removed; the role had never been created. The deploy workflows run `cdk deploy --all -c smart-tutor:mode=…`, and ADR 0016 keeps the modes apart.
  - Decision: the stack `SmartTutor-EvalsCI` with the role and its Bedrock policy from `models.py`; its own CDK entry (`infra/evals_ci_app.py`), never in `build_app`; deployed and destroyed by an admin with `make evals-ci-deploy`/`evals-ci-destroy`; imports the OIDC provider by ARN (ADR 0016's shared exception); outputs `RoleArn` for the GitHub secret.
  - Alternatives rejected: keep the runbook (hand-made, untracked, hard to remove); add it to `build_app` in both modes (each mode's `deploy --all` would own it, two apps would fight over one stack name, and a mode's teardown would delete CI's role); add it to one mode (ties CI to that mode's lifetime); a workflow deploys it (a role can't create itself; the deploy roles would need IAM rights over CI); a separate CDK project like `platform/langfuse` (it needs `infra`'s `models.py` and context; a second project for one role).
  - Consequences: one more stack an admin deploys by hand, again after a model change; tearing down native-cloud's `GitHubDeploy` would still delete the OIDC provider this role (and on-premise's deploy role) trusts — a separate follow-up.
  - Add the index row to `sdd/adr/README.md`: `| [0024](0024-ci-evals-role-is-its-own-stack.md) | The CI evals role is the stack SmartTutor-EvalsCI, outside both deployment modes, with its own CDK entry and Make targets; its Bedrock policy comes from models.py (replaces #226's hand-made role and policy JSON) |`, and in `AGENTS.md` change `` `sdd/adr/` (0001–0023) `` to `` `sdd/adr/` (0001–0024) ``.

- [ ] **Step 6: Run the infra tests.**
Run: `cd infra && uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add -A docs/runbooks sdd/adr AGENTS.md infra/tests/test_evals_ci_access.py
git commit -m "Deploy the CI evals role from its stack and drop the policy JSON (#337)"
```
