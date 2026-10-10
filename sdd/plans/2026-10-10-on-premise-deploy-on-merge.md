# On-premise deploy on merge Implementation Plan (#150)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every push to `main` builds the images and deploys on-premise mode (cdk deploy → SSM Run Command → smoke test); native-cloud deploys only when chosen.

**Architecture:** `deploy.yml` (push to `main`, or `workflow_dispatch` with a `mode`) runs `checks` (ci.yml) → `images` (new reusable `build-images.yml`, which builds and pushes the six images unless all are already in ECR) → `on-premise` (new reusable `deploy-on-premise.yml`) and, only when chosen, `native-cloud` (`deploy-pilot.yml` renamed `deploy-native-cloud.yml`, its image build moved out). `rollback.yml` takes a `mode` (default `on-premise`) and calls the mode's workflow with `infrastructure: false`. The on-premise deploy role (GitHubDeployStack, environment `on-premise`) gains permission to run only the deploy SSM document and read its result. The native-cloud GitHub environment is renamed `pilot` → `native-cloud` (CDK context `smart-tutor:github-environment`).

**Tech Stack:** GitHub Actions (reusable workflows, environments, OIDC), AWS CDK (Python), AWS CLI (SSM Run Command, ECR), pytest + PyYAML for workflow tests.

**Spec:** GitHub issue #150 (parent #145); PRD §9.11–9.12 ("On-premise, on every merge to `main`: tests … → images to ECR → `cdk deploy` → SSM Run Command on the VM … → smoke test"; "Native-cloud … runs by `workflow_dispatch`, or on every merge when `NATIVE_CLOUD_AUTO_DEPLOY=true`"); ADR 0012 "Delivery"; `docs/runbooks/on-premise-deploy.md` §3 (the manual steps this automates). The PRD already describes this behavior, so it doesn't change.

**Facts checked on 2026-10-10:**
- Repo variable `NATIVE_CLOUD_AUTO_DEPLOY=false`; since it was set, `deploy.yml`'s `deploy` job is skipped and **no images are built** (ECR's newest tag is `a8b670e`, #176). This is why on-premise can't deploy `main` today.
- GitHub environments: only `pilot` (custom branch policy `main`; variables `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_ACCOUNT_ID`). No `on-premise` or `native-cloud` environment yet: an admin creates them (Task 3 documents how).
- Live stacks: `SmartTutor-OnPremise-prod-{Host,Budgets,Config,Storage,GitHubDeploy}` and all native-cloud stacks. The on-premise role `smart-tutor-on-premise-github-deploy` already trusts `…:environment:on-premise` and can assume the CDK bootstrap roles, push to `smart-tutor/*`, and describe `SmartTutor-OnPremise-prod-*` stacks; it lacks SSM.
- Host outputs `InstanceId`, `PublicUrl`, `DeployDocumentName` (document `smart-tutor-on-premise-deploy`, parameter `ImageTag` `^[0-9a-f]{40}$`, 1800 s timeout). SSM parameter `/smart-tutor-on-premise/host/registry` is `<account>.dkr.ecr.<region>.amazonaws.com`.
- The deploy roles' maximum session is 1 hour, so a deploy job must finish within 60 minutes.

## Global Constraints

- CDK CLI pinned `aws-cdk@2.1145.0`; third-party actions pinned by full commit SHA, the same SHAs `deploy-pilot.yml` uses today (checkout `11d5960a326750d5838078e36cf38b85af677262` v4.4.0, setup-node `49933ea5288caeca8642d1e84afbd3f7d6820020` v4.4.0, setup-uv `d0cc045d04ccac9d8b7881df0226f9e82c39688e` v6.8.0, setup-helm `1a275c3b69536ee54be43f2070a358922e12c8d4` v4.3.1, configure-aws-credentials `7474bc4690e29a8392af63c5b98e7449536d5c3a` v4.3.1).
- No AWS keys and no `${{ secrets.* }}` in any workflow; credentials only via OIDC `role-to-assume: ${{ vars.AWS_ROLE_ARN }}`, `aws-region: ${{ vars.AWS_REGION }}` (environment-scoped variables, so each environment names its own role).
- `id-token: write` only on jobs that call a workflow running in an environment; workflows have no top-level `permissions`.
- Never interpolate `${{ inputs.* }}` inside a `run:` script; pass inputs through `env:`.
- Image tags are full 40-character commit SHAs; images `smart-tutor/{api,web,keycloak,agent,mcp,worker}`; web build args `VITE_API_URL=/api`, `VITE_KEYCLOAK_URL=/auth`.
- Deploys of one mode run one at a time and queue: `concurrency: {group: deploy-<mode>, cancel-in-progress: false}`.
- Each deploy job: `timeout-minutes: 60` (the role session lasts 1 hour).
- Nothing a workflow prints may contain a secret (deploy.sh never prints one; don't add `set -x`).
- Infra code style: `cd infra && uv run pytest` (ruff config in `infra/pyproject.toml` if present); docs in plain English, short sentences, as the existing runbooks.

## Review Focus

1. **The CDK deploy replaces the VM** (a new Amazon Linux 2023 image): the instance id changes and the new instance isn't in SSM for a few minutes → the workflow reads `InstanceId` *after* `cdk deploy` and waits until SSM says `Online` before `send-command` (Task 2 test `test_on_premise_reads_outputs_after_cdk_and_waits_for_ssm`).
2. **The deploy on the VM fails or times out** → the job prints the command's stdout/stderr and fails unless the status is `Success`; an `InvocationDoesNotExist` right after `send-command` counts as still pending, not as a failure (Task 2 test `test_on_premise_deploy_fails_unless_ssm_reports_success`).
3. **Re-running a deploy, or both modes in one run** → images aren't rebuilt when all six already exist (Task 2 test `test_images_are_built_only_when_missing`).
4. **A pull request or another branch reaching AWS** → only `deploy.yml` and `rollback.yml` call the environment workflows, and only those reusable workflows name `vars.AWS_ROLE_ARN` (Task 2 test `test_only_main_and_rollback_reach_the_deploy_environments`).
5. **The workflow's environment names drift from the roles' trust** → a test compares each workflow's `environment` with the CDK context / constant the role trusts (Task 2 test `test_workflow_environments_match_the_roles_trust`).

---

### Task 1: The on-premise deploy role may run the deploy document; native-cloud's environment is `native-cloud`

**Files:**
- Modify: `infra/smart_tutor_infra/names.py` (add `ModeNames.deploy_document`)
- Modify: `infra/smart_tutor_infra/stacks/host.py:322-326` (use `names.deploy_document`)
- Modify: `infra/smart_tutor_infra/stacks/github_deploy.py` (new `deploy_document` parameter and two statements)
- Modify: `infra/smart_tutor_infra/app_stacks.py` (`_on_premise` passes `deploy_document=names.deploy_document`)
- Modify: `infra/cdk.json` (`"smart-tutor:github-environment": "native-cloud"`)
- Test: `infra/tests/test_deployment_modes.py`, `infra/tests/test_synth.py`

**Interfaces:**
- Produces: `ModeNames.deploy_document -> str` (`"smart-tutor-on-premise-deploy"` in on-premise mode); `GitHubDeployStack(..., deploy_document: str | None = None)`; policy Sids `RunDeployDocument`, `ReadDeployStatus`; CDK context `smart-tutor:github-environment == "native-cloud"` (Task 2's tests read it).

- [ ] **Step 1: Write the failing tests**

In `infra/tests/test_deployment_modes.py`, replace the last three lines of `test_on_premise_deploy_role_trusts_its_own_environment_and_reads_only_its_stacks` (from `statements = ...` to the end) with:

```python
    statements = next(iter(t.find_resources("AWS::IAM::Policy").values()))["Properties"]["PolicyDocument"]["Statement"]
    assert [s["Sid"] for s in statements] == [
        "AssumeCdkBootstrapRoles",
        "EcrLogin",
        "EcrPushAppImages",
        "RunDeployDocument",
        "ReadDeployStatus",
        "ReadStackOutputs",
    ]
    (outputs,) = (s for s in statements if s["Sid"] == "ReadStackOutputs")
    assert "stack/SmartTutor-OnPremise-prod-*/*" in str(outputs["Resource"])
```

and add after that test:

```python
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
```

(`json` and `mode_names` are already imported at the top of the file.)

In `infra/tests/test_synth.py`, rename `test_deploy_role_trusts_only_the_pilot_environment_of_this_repository` to `test_deploy_role_trusts_only_the_native_cloud_environment_of_this_repository` and change its expected subject from `"repo:konica@1114311/agent-tutor@1399048529:environment:pilot"` to `"repo:konica@1114311/agent-tutor@1399048529:environment:native-cloud"`. Its Sid list (lines ~74-80) and the `Resource == "*"` check (`["EcrLogin"]`) stay as they are: native-cloud gets no SSM statements.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra && uv run pytest tests/test_deployment_modes.py tests/test_synth.py -q`
Expected: FAIL — the Sid list lacks `RunDeployDocument`; `KeyError: 'RunDeployDocument'`; `AttributeError: ... 'deploy_document'`; the native-cloud subject is still `environment:pilot`.

- [ ] **Step 3: Implement**

`infra/smart_tutor_infra/names.py`, after the `deploy_role` property:

```python
    @property
    def deploy_document(self) -> str:
        """The SSM Command document that deploys one image tag on the on-premise host (HostStack)."""
        return f"{self.data_prefix}-deploy"
```

`infra/smart_tutor_infra/stacks/host.py`, in `ssm.CfnDocument(... "DeployDocument", ...)`: replace `name=f"{names.data_prefix}-deploy",` with `name=names.deploy_document,`.

`infra/smart_tutor_infra/stacks/github_deploy.py`:
- Class docstring: after "read its mode's stack outputs, and, with `eks`, describe the EKS cluster." add " With `deploy_document` (on-premise, #150), it runs that one SSM document on the mode's instances and reads the result."
- Add the keyword parameter `deploy_document: str | None = None,` after `eks: bool = False,`.
- In `statements`, between the `EksKubeconfig` block and `ReadStackOutputs`, insert:

```python
            *(
                [
                    # SendCommand is authorized on both the document and the target instance. Only the deploy
                    # document is allowed, so the role can't run arbitrary shell commands on any instance.
                    iam.PolicyStatement(
                        sid="RunDeployDocument",
                        actions=["ssm:SendCommand"],
                        resources=[
                            f"arn:aws:ssm:{region}:{account}:document/{deploy_document}",
                            f"arn:aws:ec2:{region}:{account}:instance/*",
                        ],
                    ),
                    # Neither action supports resource-level permissions.
                    iam.PolicyStatement(
                        sid="ReadDeployStatus",
                        actions=["ssm:DescribeInstanceInformation", "ssm:GetCommandInvocation"],
                        resources=["*"],
                    ),
                ]
                if deploy_document
                else []
            ),
```

`infra/smart_tutor_infra/app_stacks.py`, in `_on_premise`'s `GitHubDeployStack(...)`, add `deploy_document=names.deploy_document,` after `github_environment=ON_PREMISE_GITHUB_ENVIRONMENT,`. Update the comment above `ON_PREMISE_GITHUB_ENVIRONMENT` to: `# The GitHub environment whose jobs may assume the on-premise deploy role (deploy-on-premise.yml, #150).`

`infra/cdk.json`: `"smart-tutor:github-environment": "pilot"` → `"smart-tutor:github-environment": "native-cloud"`.

- [ ] **Step 4: Run the infra suite**

Run: `cd infra && uv run pytest -q`
Expected: PASS (all tests). If ruff is configured: `uv run ruff check . && uv run ruff format --check .` also pass.

- [ ] **Step 5: Commit**

```bash
git add infra/
git commit -m "Let the on-premise deploy role run the deploy document; rename the native-cloud environment

#150 deploys on-premise from GitHub Actions through SSM Run Command. The role may send only the
deploy document and read its status. The native-cloud environment is named after its mode now
that the pilot is no longer the default."
```

---

### Task 2: Workflows — images, on-premise deploy on merge, native-cloud opt-in, rollback by mode

**Files:**
- Create: `.github/workflows/build-images.yml`, `.github/workflows/deploy-on-premise.yml`
- Rename + modify: `.github/workflows/deploy-pilot.yml` → `.github/workflows/deploy-native-cloud.yml` (`git mv`)
- Modify: `.github/workflows/deploy.yml`, `.github/workflows/rollback.yml`
- Test: `infra/tests/test_workflows.py` (rewrite)

**Interfaces:**
- Consumes: Task 1's `smart-tutor:github-environment == "native-cloud"`, `ON_PREMISE_GITHUB_ENVIRONMENT == "on-premise"` (`smart_tutor_infra.app_stacks`), the Host outputs `InstanceId`, `PublicUrl`, `DeployDocumentName`.
- Produces: reusable `build-images.yml` (inputs `image_tag: string`, `environment: string`), `deploy-on-premise.yml` and `deploy-native-cloud.yml` (inputs `image_tag: string`, `infrastructure: boolean`); `deploy.yml` dispatch input `mode` (choice `on-premise`|`native-cloud`, default `on-premise`); `rollback.yml` inputs `mode` (same choice) and `image_tag`.

- [ ] **Step 1: Rewrite `infra/tests/test_workflows.py`** (full content):

```python
"""Static checks of the GitHub Actions workflows (#59, #150): what runs, when, and with which AWS access."""

import json
import re
from pathlib import Path
from typing import Any

import yaml

from smart_tutor_infra.app_stacks import ON_PREMISE_GITHUB_ENVIRONMENT
from tests.test_synth import CDK_CONTEXT

WORKFLOWS = Path(__file__).parents[2] / ".github/workflows"
RUNBOOKS = WORKFLOWS.parents[1] / "docs/runbooks"
IMAGES = ("api", "web", "keycloak", "agent", "mcp", "worker")
ENVIRONMENT_WORKFLOWS = ("build-images.yml", "deploy-on-premise.yml", "deploy-native-cloud.yml")
ADDON_VERSIONS = {
    "aws-load-balancer-controller": "3.5.0",
    "external-secrets": "2.11.0",
    "metrics-server": "3.14.0",
}


def workflow(name: str) -> dict[str, Any]:
    doc = yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))
    doc["on"] = doc.pop(True, doc.get("on"))  # YAML 1.1 reads the bare key `on` as True
    return doc


def steps_text(job: dict[str, Any]) -> str:
    return "\n".join(str(s.get("run", "")) + str(s.get("uses", "")) + str(s.get("with", "")) for s in job["steps"])


def only_job(name: str) -> dict[str, Any]:
    (job,) = workflow(name)["jobs"].values()
    return job


def step(job: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in job["steps"] if s.get("name") == name)


def index_of(job: dict[str, Any], marker: str) -> int:
    return next(i for i, s in enumerate(job["steps"]) if marker in str(s.get("run", "")) + str(s.get("uses", "")))


def images_job() -> dict[str, Any]:
    return only_job("build-images.yml")


def on_premise_job() -> dict[str, Any]:
    return only_job("deploy-on-premise.yml")


def native_cloud_job() -> dict[str, Any]:
    return only_job("deploy-native-cloud.yml")


# --- Triggers and access ---------------------------------------------------------------------------------------


def test_ci_is_reusable_and_runs_infra_tests() -> None:
    ci = workflow("ci.yml")

    # a push to main runs it through deploy.yml
    assert set(ci["on"]) == {"pull_request", "workflow_call"}
    text = steps_text(ci["jobs"]["infra"])
    # chart tests skip without helm
    assert "azure/setup-helm" in text
    assert "uv run pytest" in text
    # the production lint, as the runbook deploys it
    assert "values-prod.yaml" in steps_text(ci["jobs"]["helm"])
    assert {"backend", "web", "design", "helm", "infra"} <= set(ci["jobs"])


def test_deploy_runs_on_push_to_main_or_by_hand_with_a_mode() -> None:
    on = workflow("deploy.yml")["on"]
    assert on["push"] == {"branches": ["main"]}
    mode = on["workflow_dispatch"]["inputs"]["mode"]
    assert mode["type"] == "choice"
    assert mode["options"] == ["on-premise", "native-cloud"]
    assert mode["default"] == "on-premise"


def test_rollback_is_manual_and_defaults_to_on_premise() -> None:
    inputs = workflow("rollback.yml")["on"]["workflow_dispatch"]["inputs"]
    assert set(workflow("rollback.yml")["on"]) == {"workflow_dispatch"}
    assert inputs["mode"]["options"] == ["on-premise", "native-cloud"]
    assert inputs["mode"]["default"] == "on-premise"
    assert inputs["image_tag"]["required"] is True


def test_only_main_and_rollback_reach_the_deploy_environments() -> None:
    for name in ENVIRONMENT_WORKFLOWS:
        assert set(workflow(name)["on"]) == {"workflow_call"}, name
    callers = 0
    for name in ("deploy.yml", "rollback.yml"):
        wf = workflow(name)
        # id-token is granted only to the jobs that call a workflow running in an environment
        assert "permissions" not in wf, name
        for job_name, job in wf["jobs"].items():
            if job.get("uses", "").removeprefix("./.github/workflows/") in ENVIRONMENT_WORKFLOWS:
                callers += 1
                assert job["permissions"] == {"contents": "read", "id-token": "write"}, (name, job_name)
            else:
                assert job["permissions"] == {"contents": "read"}, (name, job_name)
    assert callers == 5  # deploy: images, on-premise, native-cloud; rollback: on-premise, native-cloud
    # Only the environment workflows name a deploy role (openwiki-update.yml has its own Bedrock-only role).
    for path in WORKFLOWS.glob("*.yml"):
        if path.name not in ENVIRONMENT_WORKFLOWS:
            assert "vars.AWS_ROLE_ARN" not in path.read_text(encoding="utf-8"), path.name
    assert "id-token" not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_workflow_environments_match_the_roles_trust() -> None:
    # Each deploy role trusts exactly one environment (GitHubDeployStack); a rename on one side alone locks out the deploy.
    assert on_premise_job()["environment"] == ON_PREMISE_GITHUB_ENVIRONMENT == "on-premise"
    assert native_cloud_job()["environment"] == CDK_CONTEXT["smart-tutor:github-environment"] == "native-cloud"
    assert images_job()["environment"] == "${{ inputs.environment }}"


def test_no_long_lived_aws_keys() -> None:
    for path in WORKFLOWS.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        assert "AWS_ACCESS_KEY_ID" not in text and "AWS_SECRET_ACCESS_KEY" not in text, path.name
    for name in ("ci.yml", "deploy.yml", "rollback.yml", *ENVIRONMENT_WORKFLOWS):
        assert "${{ secrets." not in (WORKFLOWS / name).read_text(encoding="utf-8"), name
    for job in (images_job(), on_premise_job(), native_cloud_job()):
        creds = next(s for s in job["steps"] if "configure-aws-credentials" in str(s.get("uses")))
        assert creds["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
        assert creds["with"]["aws-region"] == "${{ vars.AWS_REGION }}"


def test_third_party_actions_are_pinned_and_set_up_before_credentials() -> None:
    for job in (images_job(), on_premise_job(), native_cloud_job()):
        steps = job["steps"]
        for ref in (str(s["uses"]) for s in steps if "uses" in s):
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
        creds = index_of(job, "configure-aws-credentials")
        for i, s in enumerate(steps):
            if "setup-" in str(s.get("uses")):
                assert i < creds, s["uses"]


def test_no_expressions_from_inputs_inside_run_scripts() -> None:
    for name in ("deploy.yml", "rollback.yml", *ENVIRONMENT_WORKFLOWS):
        for job in workflow(name)["jobs"].values():
            for s in job.get("steps", []):
                assert "${{ inputs." not in str(s.get("run", "")), (name, s.get("name"))


def test_deploy_jobs_have_a_time_limit_within_the_role_session() -> None:
    # The deploy roles' sessions last at most 1 hour (GitHubDeployStack).
    for job in (on_premise_job(), native_cloud_job()):
        assert job["timeout-minutes"] == 60
    assert images_job()["timeout-minutes"] == 30


def test_deployments_of_one_mode_queue_and_never_cancel() -> None:
    assert on_premise_job()["concurrency"] == {"group": "deploy-on-premise", "cancel-in-progress": False}
    assert native_cloud_job()["concurrency"] == {"group": "deploy-native-cloud", "cancel-in-progress": False}


# --- deploy.yml: what a push and a manual run deploy ---------------------------------------------------------


def test_a_push_checks_builds_then_deploys_on_premise() -> None:
    jobs = workflow("deploy.yml")["jobs"]
    assert jobs["checks"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["images"]["needs"] == "checks"
    assert jobs["images"]["uses"] == "./.github/workflows/build-images.yml"
    # a push builds with the on-premise role; a manual run with the role of the mode it deploys
    assert jobs["images"]["with"] == {"image_tag": "${{ github.sha }}", "environment": "${{ inputs.mode || 'on-premise' }}"}
    on_premise = jobs["on-premise"]
    assert on_premise["needs"] == "images"
    assert on_premise["uses"] == "./.github/workflows/deploy-on-premise.yml"
    assert on_premise["with"] == {"image_tag": "${{ github.sha }}", "infrastructure": True}
    assert on_premise["if"] == "github.event_name == 'push' || inputs.mode == 'on-premise'"


def test_native_cloud_deploys_only_when_chosen() -> None:
    native_cloud = workflow("deploy.yml")["jobs"]["native-cloud"]
    assert native_cloud["needs"] == "images"
    assert native_cloud["uses"] == "./.github/workflows/deploy-native-cloud.yml"
    assert native_cloud["with"] == {"image_tag": "${{ github.sha }}", "infrastructure": True}
    # Unset or anything but `true` keeps it off (#150 made it opt-in; it used to be opt-out).
    assert native_cloud["if"] == (
        "(github.event_name == 'push' && vars.NATIVE_CLOUD_AUTO_DEPLOY == 'true') || inputs.mode == 'native-cloud'"
    )


def test_rollback_redeploys_the_chosen_mode_without_infrastructure() -> None:
    jobs = workflow("rollback.yml")["jobs"]
    assert jobs["on-premise"]["if"] == "inputs.mode == 'on-premise'"
    assert jobs["on-premise"]["uses"] == "./.github/workflows/deploy-on-premise.yml"
    assert jobs["native-cloud"]["if"] == "inputs.mode == 'native-cloud'"
    assert jobs["native-cloud"]["uses"] == "./.github/workflows/deploy-native-cloud.yml"
    for job in jobs.values():
        assert job["with"] == {"image_tag": "${{ inputs.image_tag }}", "infrastructure": False}


# --- build-images.yml ------------------------------------------------------------------------------------------


def test_images_are_built_for_the_commit_and_pushed() -> None:
    job = images_job()
    text = steps_text(job)
    checkout = next(s for s in job["steps"] if "actions/checkout" in str(s.get("uses")))
    assert checkout["with"]["ref"] == "${{ inputs.image_tag }}"
    for image in IMAGES:
        assert f'"$REGISTRY/smart-tutor/{image}:$IMAGE_TAG"' in text, image
    for target in ("api", "agent", "mcp", "worker"):
        assert f"--target {target}" in text
    assert "VITE_API_URL=/api" in text and "VITE_KEYCLOAK_URL=/auth" in text
    assert "docker push" in text
    # The shared registry is the account's, in the role's region (both modes push to it).
    assert "aws sts get-caller-identity --query Account" in text
    assert index_of(job, "docker build") < index_of(job, "docker push")


def test_images_are_built_only_when_missing() -> None:
    job = images_job()
    check = step(job, "Check which images exist")
    assert check["id"] == "existing"
    for image in IMAGES:
        assert image in check["run"]
    assert "describe-images" in check["run"] and "GITHUB_OUTPUT" in check["run"]
    for s in job["steps"]:
        run = str(s.get("run", ""))
        if "docker build" in run or "docker push" in run or "docker login" in run:
            assert s["if"] == "steps.existing.outputs.all != 'true'", s.get("name")
    assert index_of(job, "describe-images") < index_of(job, "docker build")


# --- deploy-on-premise.yml -------------------------------------------------------------------------------------


def test_on_premise_checks_the_tag_and_the_images_before_deploying() -> None:
    job = on_premise_job()
    tag = index_of(job, "^[0-9a-f]{40}$")
    checkout = index_of(job, "actions/checkout")
    creds = index_of(job, "configure-aws-credentials")
    images = index_of(job, "describe-images")
    cdk = index_of(job, "aws-cdk@")
    # a malformed tag is rejected before checkout and sign-in; missing images before anything changes
    assert tag < checkout < creds < images < cdk
    assert job["steps"][checkout]["with"]["ref"] == "${{ inputs.image_tag }}"
    for image in IMAGES:
        assert image in job["steps"][images]["run"]


def test_on_premise_runs_cdk_only_with_infrastructure() -> None:
    job = on_premise_job()
    cdk = job["steps"][index_of(job, "aws-cdk@")]
    assert "npx --yes aws-cdk@2.1145.0 deploy --all --require-approval never -c smart-tutor:mode=on-premise" in cdk["run"]
    assert cdk["if"] == "inputs.infrastructure"
    assert cdk["working-directory"] == "infra"
    for s in job["steps"]:
        if "setup-node" in str(s.get("uses")) or "setup-uv" in str(s.get("uses")):
            assert s["if"] == "inputs.infrastructure"


def test_on_premise_reads_outputs_after_cdk_and_waits_for_ssm() -> None:
    job = on_premise_job()
    outputs = step(job, "Read the stack outputs")
    # the outputs are read after cdk deploy, which may have replaced the instance
    assert index_of(job, "aws-cdk@") < job["steps"].index(outputs)
    assert "SmartTutor-OnPremise-prod-Host" in outputs["run"]
    for key in ("InstanceId", "PublicUrl", "DeployDocumentName"):
        assert key in outputs["run"]
    assert outputs["run"].count("!= None") == 3 and outputs["run"].count("::error::") == 3
    wait = step(job, "Wait until the VM is online in SSM")
    assert "describe-instance-information" in wait["run"] and "Online" in wait["run"]
    assert job["steps"].index(outputs) < job["steps"].index(wait) < index_of(job, "send-command")


def test_on_premise_deploy_fails_unless_ssm_reports_success() -> None:
    run = step(on_premise_job(), "Deploy the images on the VM (SSM Run Command)")["run"]
    assert '--document-name "$DEPLOY_DOCUMENT"' in run
    assert '--instance-ids "$INSTANCE_ID"' in run
    assert '--parameters "ImageTag=$IMAGE_TAG"' in run
    # right after send-command the invocation may not exist yet: that is pending, not a failure
    assert "|| echo Pending" in run
    assert "Pending|InProgress|Delayed" in run
    # the VM's output (it never holds a secret) is printed, then anything but Success fails the job
    assert "StandardOutputContent" in run and "StandardErrorContent" in run
    assert '[[ "$status" == Success ]]' in run
    # the poll outlasts the document's 30-minute limit but stays inside the job's 60 minutes
    polls = int(re.search(r"seq (\d+)", run).group(1))
    assert 1800 < polls * 10 < 2400


def test_on_premise_smoke_test_runs_last_against_the_public_url() -> None:
    job = on_premise_job()
    steps = job["steps"]
    last = steps[-1]
    run = str(last["run"])
    assert last.get("name") == "Smoke test the public address"
    assert 'python3 deploy/pilot/smoke_test.py "$PUBLIC_URL"' in run
    # the summary names the deploy only after the smoke test passed
    assert run.index("smoke_test.py") < run.index("GITHUB_STEP_SUMMARY")
    assert sum("GITHUB_STEP_SUMMARY" in str(s.get("run", "")) for s in steps) == 1
    assert index_of(job, "send-command") < len(steps) - 1


# --- deploy-native-cloud.yml (the former deploy-pilot.yml) ------------------------------------------------------


def test_native_cloud_no_longer_builds_images() -> None:
    text = steps_text(native_cloud_job())
    assert "docker build" not in text and "docker push" not in text


def test_native_cloud_deploys_in_order() -> None:
    text = steps_text(native_cloud_job())
    order = [
        "^[0-9a-f]{40}$",
        "describe-images",
        "aws-cdk@2.1145.0 deploy --all --require-approval never -c smart-tutor:mode=native-cloud",
        "aws eks update-kubeconfig --name smart-tutor-prod",
        "helm upgrade --install aws-load-balancer-controller",
        "helm upgrade --install smart-tutor deploy/helm/smart-tutor",
        "deploy/pilot/smoke_test.py",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_native_cloud_checks_tag_and_images_and_runs_cdk_only_with_infrastructure() -> None:
    job = native_cloud_job()
    steps = job["steps"]
    checkout = next(s for s in steps if "actions/checkout" in str(s.get("uses")))
    assert checkout["with"]["ref"] == "${{ inputs.image_tag }}"  # the chart that matches the images
    assert index_of(job, "^[0-9a-f]{40}$") < steps.index(checkout) < index_of(job, "configure-aws-credentials")
    images = steps[index_of(job, "describe-images")]
    assert "if" not in images  # every deploy checks, not only a rollback
    for repo in IMAGES:
        assert repo in images["run"]
    assert steps[index_of(job, "aws-cdk@")]["if"] == "inputs.infrastructure"


def test_native_cloud_release_uses_the_tag_and_the_stack_outputs() -> None:
    text = steps_text(native_cloud_job())
    assert 'global.imageTag="$IMAGE_TAG"' in text
    for output in ("RegistryUri", "CloudFrontUrl", "VpcId", "DocumentsBucketName", "IngestQueueUrl"):
        assert output in text
    assert 'global.documentsBucket="$DOCUMENTS_BUCKET"' in text
    assert 'global.ingestQueueUrl="$INGEST_QUEUE_URL"' in text
    assert "values-prod.yaml" in text and "--timeout 15m" in text


def test_native_cloud_release_waits_with_the_legacy_strategy() -> None:
    # Helm 4's default watcher strategy sits out the whole --timeout on every non-Job hook (SecretStore,
    # ExternalSecrets, ConfigMap), so the first install outran the job's 60 minutes. Legacy waits as Helm 3 did.
    release = step(native_cloud_job(), "Release the app (Helm)")
    assert "--wait=legacy --timeout 15m" in release["run"]
    runbook = (RUNBOOKS / "pilot-deploy.md").read_text(encoding="utf-8")
    lines = re.findall(r"helm upgrade --install smart-tutor .*", runbook)
    assert lines
    for line in lines:
        assert "--wait=legacy --timeout 15m" in line, line


def test_native_cloud_stack_outputs_fail_loudly_when_missing() -> None:
    run = str(step(native_cloud_job(), "Read the stack outputs")["run"])
    assert run.count("!= None") == 5
    assert run.count("::error::") == 5


def test_native_cloud_release_is_followed_by_an_in_cluster_service_check() -> None:
    steps = native_cloud_job()["steps"]
    names = [s.get("name") for s in steps]
    check = steps[names.index("Check the in-cluster services")]
    assert (
        names.index("Release the app (Helm)")
        < names.index("Check the in-cluster services")
        < names.index("Smoke test the public address")
    )
    assert "http://agent/healthz" in check["run"]
    assert "http://mcp-server/mcp" in check["run"]


def test_native_cloud_add_ons_match_the_runbook_versions() -> None:
    text = steps_text(native_cloud_job())
    runbook = (RUNBOOKS / "pilot-deploy.md").read_text(encoding="utf-8")
    for chart, version in ADDON_VERSIONS.items():
        pattern = rf"upgrade --install {chart} \S+ --version {re.escape(version)}"
        assert re.search(pattern, text), chart
        assert re.search(pattern, runbook), chart


def test_native_cloud_smoke_test_runs_last_against_the_cloudfront_url() -> None:
    steps = native_cloud_job()["steps"]
    last = next(s for s in reversed(steps) if "failure()" not in str(s.get("if")))
    run = str(last["run"])
    assert "deploy/pilot/smoke_test.py" in run and "CLOUDFRONT_URL" in run
    assert run.index("smoke_test.py") < run.index("GITHUB_STEP_SUMMARY")
    assert sum("GITHUB_STEP_SUMMARY" in str(s.get("run", "")) for s in steps) == 1


def test_native_cloud_failed_deploys_print_diagnostics() -> None:
    last = native_cloud_job()["steps"][-1]
    # also when the job times out or is cancelled, which is when a stuck release needs explaining
    assert last["if"] == "failure() || cancelled()"
    assert "helm -n smart-tutor history" in str(last["run"])


def test_workflow_files_parse_as_json_compatible_yaml() -> None:
    # Guards against tabs and duplicate keys slipping into the new files.
    for name in ("deploy.yml", "rollback.yml", *ENVIRONMENT_WORKFLOWS):
        json.dumps(workflow(name))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: FAIL — `FileNotFoundError` for `build-images.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`; `deploy.yml` has no `workflow_dispatch`.

- [ ] **Step 3: Create `.github/workflows/build-images.yml`**

```yaml
# Builds the six app images for one commit and pushes them to the shared ECR repositories, tagged with the full commit
# SHA (#150). Called by deploy.yml before either mode deploys. Skips the build when all six are already in ECR, so a
# re-run or a second mode never pushes the same tag twice. Signs in with the deploy role of the environment it is given.
name: build-images

on:
  workflow_call:
    inputs:
      image_tag:
        description: Full commit SHA to build and tag the images with
        type: string
        required: true
      environment:
        description: GitHub environment whose deploy role pushes the images (on-premise or native-cloud)
        type: string
        required: true

jobs:
  build:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    timeout-minutes: 30
    env:
      AWS_REGION: ${{ vars.AWS_REGION }}
      IMAGE_TAG: ${{ inputs.image_tag }}
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with:
          ref: ${{ inputs.image_tag }}

      - uses: aws-actions/configure-aws-credentials@7474bc4690e29a8392af63c5b98e7449536d5c3a # v4.3.1
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      # ECR is shared by both modes (native-cloud's Registry stack): the account's registry in the region.
      - name: Check which images exist
        id: existing
        run: |
          account=$(aws sts get-caller-identity --query Account --output text)
          echo "REGISTRY=$account.dkr.ecr.$AWS_REGION.amazonaws.com" >> "$GITHUB_ENV"
          all=true
          for repo in api web keycloak agent mcp worker; do
            if aws ecr describe-images --repository-name "smart-tutor/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null 2>&1; then
              echo "smart-tutor/$repo:$IMAGE_TAG is already in ECR"
            else
              all=false
            fi
          done
          echo "all=$all" >> "$GITHUB_OUTPUT"

      - name: Sign in to ECR
        if: steps.existing.outputs.all != 'true'
        run: aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"

      - name: Build the images
        if: steps.existing.outputs.all != 'true'
        run: |
          docker build --target api -t "$REGISTRY/smart-tutor/api:$IMAGE_TAG" backend
          docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$REGISTRY/smart-tutor/web:$IMAGE_TAG" web
          docker build -t "$REGISTRY/smart-tutor/keycloak:$IMAGE_TAG" deploy/keycloak
          docker build --target agent -t "$REGISTRY/smart-tutor/agent:$IMAGE_TAG" backend
          docker build --target mcp -t "$REGISTRY/smart-tutor/mcp:$IMAGE_TAG" backend
          docker build --target worker -t "$REGISTRY/smart-tutor/worker:$IMAGE_TAG" backend

      - name: Push the images
        if: steps.existing.outputs.all != 'true'
        run: |
          for repo in api web keycloak agent mcp worker; do docker push "$REGISTRY/smart-tutor/$repo:$IMAGE_TAG"; done
```

Note: the "Sign in to ECR" step's `run` contains `docker login`, so the test requires its `if`.

- [ ] **Step 4: Create `.github/workflows/deploy-on-premise.yml`**

```yaml
# Deploys on-premise mode (PRD §9.12, ADR 0012, #150): cdk deploy, then SSM Run Command runs deploy.sh with the tag on
# the VM, then the smoke test. Called by deploy.yml (every push to main, after the checks and the images) and
# rollback.yml. Signs in with the on-premise deploy role, which trusts only jobs in the `on-premise` environment.
# Runbook: docs/runbooks/on-premise-deploy.md.
name: deploy-on-premise

on:
  workflow_call:
    inputs:
      image_tag:
        description: Commit SHA whose images to deploy
        type: string
        required: true
      infrastructure:
        description: Run cdk deploy first (false for a rollback, which keeps the deploy files already on the VM)
        type: boolean
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: on-premise
    # One deployment at a time; a queued one waits instead of cancelling the running one.
    concurrency:
      group: deploy-on-premise
      cancel-in-progress: false
    # The deploy role's session lasts 1 hour.
    timeout-minutes: 60
    env:
      AWS_REGION: ${{ vars.AWS_REGION }}
      IMAGE_TAG: ${{ inputs.image_tag }}
      JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION: "1"
    steps:
      # Reject a malformed tag before checking out or signing in.
      - name: Check the image tag
        run: |
          [[ "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::image_tag must be a full 40-character commit SHA"; exit 1; }

      # The smoke test (and, with infrastructure, the CDK app and deploy files) come from the deployed commit.
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with:
          ref: ${{ inputs.image_tag }}

      # Setup actions run before the AWS credentials exist in the environment.
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        if: inputs.infrastructure
        with:
          node-version: 22
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0
        if: inputs.infrastructure

      - uses: aws-actions/configure-aws-credentials@7474bc4690e29a8392af63c5b98e7449536d5c3a # v4.3.1
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      - name: Check the images exist
        run: |
          for repo in api web keycloak agent mcp worker; do
            aws ecr describe-images --repository-name "smart-tutor/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null \
              || { echo "::error::smart-tutor/$repo:$IMAGE_TAG is not in ECR (it keeps the last 30 images)"; exit 1; }
          done

      # Uploads deploy/ as the bundle the SSM document unpacks. A new Amazon Linux image replaces the instance here.
      - name: Deploy the infrastructure (CDK)
        if: inputs.infrastructure
        working-directory: infra
        run: |
          uv sync --frozen
          npx --yes aws-cdk@2.1145.0 deploy --all --require-approval never -c smart-tutor:mode=on-premise

      - name: Read the stack outputs
        run: |
          output() {
            aws cloudformation describe-stacks --stack-name SmartTutor-OnPremise-prod-Host \
              --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
          }
          instance_id=$(output InstanceId)
          [[ -n "$instance_id" && "$instance_id" != None ]] || { echo "::error::SmartTutor-OnPremise-prod-Host has no InstanceId output"; exit 1; }
          public_url=$(output PublicUrl)
          [[ -n "$public_url" && "$public_url" != None ]] || { echo "::error::SmartTutor-OnPremise-prod-Host has no PublicUrl output"; exit 1; }
          deploy_document=$(output DeployDocumentName)
          [[ -n "$deploy_document" && "$deploy_document" != None ]] || { echo "::error::SmartTutor-OnPremise-prod-Host has no DeployDocumentName output"; exit 1; }
          {
            echo "INSTANCE_ID=$instance_id"
            echo "PUBLIC_URL=$public_url"
            echo "DEPLOY_DOCUMENT=$deploy_document"
          } >> "$GITHUB_ENV"

      # A replaced instance installs Docker and registers with SSM within a few minutes of starting.
      - name: Wait until the VM is online in SSM
        run: |
          status=None
          for _ in $(seq 60); do
            status=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
              --query "InstanceInformationList[0].PingStatus" --output text)
            [[ "$status" == Online ]] && exit 0
            sleep 10
          done
          echo "::error::$INSTANCE_ID is not Online in SSM after 10 minutes (last status: $status)"
          exit 1

      # deploy.sh prints no secret, so its output is safe to show here. The document allows 30 minutes.
      - name: Deploy the images on the VM (SSM Run Command)
        run: |
          command_id=$(aws ssm send-command --document-name "$DEPLOY_DOCUMENT" --instance-ids "$INSTANCE_ID" \
            --parameters "ImageTag=$IMAGE_TAG" --comment "Deploy $IMAGE_TAG (run $GITHUB_RUN_ID)" \
            --query Command.CommandId --output text)
          echo "SSM command $command_id on $INSTANCE_ID"
          status=Pending
          for _ in $(seq 200); do
            sleep 10
            # Right after send-command the invocation may not exist yet.
            status=$(aws ssm get-command-invocation --command-id "$command_id" --instance-id "$INSTANCE_ID" \
              --query Status --output text 2> /dev/null || echo Pending)
            case "$status" in Pending|InProgress|Delayed) ;; *) break ;; esac
          done
          invocation() {
            aws ssm get-command-invocation --command-id "$command_id" --instance-id "$INSTANCE_ID" --query "$1" --output text
          }
          invocation StandardOutputContent
          invocation StandardErrorContent >&2
          [[ "$status" == Success ]] || { echo "::error::The deploy on the VM ended with status $status (output above)"; exit 1; }

      - name: Smoke test the public address
        run: |
          python3 deploy/pilot/smoke_test.py "$PUBLIC_URL"
          echo "Deployed \`$IMAGE_TAG\` to $PUBLIC_URL" >> "$GITHUB_STEP_SUMMARY"
```

(`seq 200` × 10 s ≈ 33 minutes: longer than the document's 30 minutes, inside the job's 60.)

- [ ] **Step 5: Rename and change the native-cloud workflow**

Run: `git mv .github/workflows/deploy-pilot.yml .github/workflows/deploy-native-cloud.yml`

Then edit `.github/workflows/deploy-native-cloud.yml`:
1. Header comment (lines 1-2) becomes:
   ```yaml
   # Deploys native-cloud mode (PRD §9.12, #59): cdk deploy, the cluster add-ons, and the Helm release. Opt-in since #150:
   # deploy.yml calls it when started by hand with mode native-cloud, or on a push when the repository variable
   # NATIVE_CLOUD_AUTO_DEPLOY is `true`; rollback.yml calls it with infrastructure false. deploy.yml builds the images first.
   # Signs in with the native-cloud deploy role (#55), which trusts only jobs in the `native-cloud` environment.
   ```
2. `name: deploy-pilot` → `name: deploy-native-cloud`.
3. Input `build` → `infrastructure`, description `Deploy the infrastructure with CDK first (false for a rollback)`.
4. `environment: pilot` → `environment: native-cloud`; concurrency `group: deploy-pilot` → `group: deploy-native-cloud`.
5. Step "Check the rollback tag": rename to "Check the image tag" and **remove its `if:`** (every deploy checks).
6. Comment above checkout: `# The chart and smoke test come from the deployed commit, so they match its images.`
7. `if: inputs.build` on setup-node, setup-uv, and "Deploy the infrastructure (CDK)" → `if: inputs.infrastructure`.
8. Step "Check the images to roll back to exist": rename to "Check the images exist", **remove its `if:`**.
9. **Delete** the steps "Build the images" and "Push the images".
Everything else (outputs, kubeconfig, add-ons, Helm release, in-cluster check, smoke test, diagnostics) stays byte-for-byte.

- [ ] **Step 6: Rewrite `.github/workflows/deploy.yml`**

```yaml
# Every push to main: the CI checks, the images, then the on-premise deploy (PRD §9.12, ADR 0012, #150).
# Native-cloud is opt-in: run this workflow by hand with mode native-cloud, or set the repository variable
# NATIVE_CLOUD_AUTO_DEPLOY to `true` to deploy it on every push as well (unset or anything else keeps it off).
# Runbooks: docs/runbooks/on-premise-deploy.md, docs/runbooks/pilot-deploy.md (native-cloud).
name: deploy

on:
  push:
    branches: [main]
  workflow_dispatch:
    inputs:
      mode:
        description: Deployment mode to deploy this commit to
        type: choice
        options: [on-premise, native-cloud]
        default: on-premise

jobs:
  checks:
    permissions:
      contents: read
    uses: ./.github/workflows/ci.yml

  images:
    needs: checks
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the deploy environment
    uses: ./.github/workflows/build-images.yml
    with:
      image_tag: ${{ github.sha }}
      # A push builds with the on-premise role; a manual run with the role of the mode it deploys.
      environment: ${{ inputs.mode || 'on-premise' }}

  on-premise:
    needs: images
    if: github.event_name == 'push' || inputs.mode == 'on-premise'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `on-premise` environment
    uses: ./.github/workflows/deploy-on-premise.yml
    with:
      image_tag: ${{ github.sha }}
      infrastructure: true

  native-cloud:
    needs: images
    if: (github.event_name == 'push' && vars.NATIVE_CLOUD_AUTO_DEPLOY == 'true') || inputs.mode == 'native-cloud'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `native-cloud` environment
    uses: ./.github/workflows/deploy-native-cloud.yml
    with:
      image_tag: ${{ github.sha }}
      infrastructure: true
```

- [ ] **Step 7: Rewrite `.github/workflows/rollback.yml`**

```yaml
# Redeploys an earlier commit's images, without CDK or a build (#59, #150). Runbooks: docs/runbooks/on-premise-deploy.md
# (on-premise keeps the deploy files of the last cdk deploy), docs/runbooks/pilot-deploy.md (native-cloud).
# The deploy environments only accept runs from main: start it from main with the SHA to go back to.
name: rollback

on:
  workflow_dispatch:
    inputs:
      mode:
        description: Deployment mode to roll back
        type: choice
        options: [on-premise, native-cloud]
        default: on-premise
      image_tag:
        description: Full commit SHA of an earlier deploy (its images must still be in ECR)
        type: string
        required: true

jobs:
  on-premise:
    if: inputs.mode == 'on-premise'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `on-premise` environment
    uses: ./.github/workflows/deploy-on-premise.yml
    with:
      image_tag: ${{ inputs.image_tag }}
      infrastructure: false

  native-cloud:
    if: inputs.mode == 'native-cloud'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `native-cloud` environment
    uses: ./.github/workflows/deploy-native-cloud.yml
    with:
      image_tag: ${{ inputs.image_tag }}
      infrastructure: false
```

- [ ] **Step 8: Run the tests**

Run: `cd infra && uv run pytest -q`
Expected: PASS. If `actionlint` is available (`actionlint --version`), also run `actionlint .github/workflows/*.yml` and fix what it reports; skip if it isn't installed.

- [ ] **Step 9: Commit**

```bash
git add .github/workflows infra/tests/test_workflows.py
git commit -m "Deploy on-premise on every merge to main; native-cloud is opt-in (#150)

The images were built only inside the native-cloud deploy, so turning that off stopped images
reaching ECR. A separate job now builds them, on-premise deploys through cdk deploy and SSM Run
Command with a smoke test, and native-cloud runs only by hand or with NATIVE_CLOUD_AUTO_DEPLOY=true."
```

---

### Task 3: Docs lead with on-premise; native-cloud is optional

**Files:**
- Modify: `docs/runbooks/on-premise-deploy.md`
- Modify: `README.md`
- Modify: `docs/runbooks/pilot-deploy.md`, `docs/runbooks/pilot-teardown.md`, `docs/runbooks/pilot-teardown.ps1`, `docs/runbooks/pilot-aws-prerequisites.md`, `docs/runbooks/pilot-environment-overview.md`
- Modify: `docs/architecture/solution-architecture.md` (only the references to `deploy-pilot.yml`, the `pilot` environment, and the `deploy-pilot` concurrency group, lines ~209-293 and ~417)
- Test: `infra/tests/test_workflows.py` (one docs test)

**Interfaces:**
- Consumes: workflow names from Task 2 (`deploy.yml` with `mode`, `build-images.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`, `rollback.yml` with `mode`), environments `on-premise` / `native-cloud`, Sids from Task 1.

- [ ] **Step 1: Write the failing test** (append to `infra/tests/test_workflows.py`)

```python
def test_runbooks_name_the_current_workflows_and_environments() -> None:
    docs = [*RUNBOOKS.glob("*.md"), *RUNBOOKS.glob("*.ps1"), WORKFLOWS.parents[1] / "README.md"]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "deploy-pilot.yml" not in text, path.name
        assert "environment `pilot`" not in text and "`pilot` environment" not in text, path.name
    on_premise = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    for needle in ("deploy-on-premise.yml", "build-images.yml", "rollback.yml", "gh api -X PUT", "on-premise"):
        assert needle in on_premise, needle
```

Run: `cd infra && uv run pytest tests/test_workflows.py -q -k runbooks` → FAIL (`deploy-pilot.yml` in pilot-deploy.md).

- [ ] **Step 2: `docs/runbooks/on-premise-deploy.md`**

1. Title: `# On-premise deploy (#148, #149, #150, #153)`. Intro: replace "This runbook covers the first deploy and a manual redeploy." with "Every merge to `main` deploys on-premise automatically (section 3). This runbook also covers the one-time setup, the first deploy, and a deploy by hand." and remove "Deploy on merge is #150."
2. §1 "Before you start", the ECR bullet: "…and hold images for the commit you want. `deploy.yml` builds and pushes them for every merge to `main` (`build-images.yml`), tagged with the full commit SHA. On-premise needs `api`, `web`, `keycloak`, `agent`, `mcp`, and `worker`. A commit merged while no images were built (before #150, while `NATIVE_CLOUD_AUTO_DEPLOY=false`) has none: build them by hand (section 4, "Build images by hand")."
3. Insert a new **§3 "Deploy on merge (#150)"** after §2 and renumber the following sections (3→4 … 7→8) and every in-document "section N"/"step N" reference to them (e.g. "Run step 3 again" → "Run step 4 again"; "(section 6)" → "(section 7)"; "run step 2" stays). Content:
   - **What runs:** on every push to `main`, `deploy.yml` runs the CI checks, then `build-images.yml` (builds the six images and pushes them unless all six are already there), then `deploy-on-premise.yml` in the GitHub environment `on-premise`: it checks the images exist, runs `cdk deploy --all -c smart-tutor:mode=on-premise` (uploading `deploy/` as the bundle), reads the Host outputs, waits until the VM is `Online` in SSM (a deploy that replaces the instance gives it a new id), runs the SSM document with the commit SHA and prints its output, and runs `deploy/pilot/smoke_test.py` against `PublicUrl`. The run fails if any step fails, including the smoke test. One on-premise deploy runs at a time; a later merge waits (concurrency group `deploy-on-premise`). Native-cloud doesn't deploy unless chosen (section "Native-cloud is optional" in `pilot-deploy.md`).
   - **One-time setup** (an admin, once):
     1. Deploy the on-premise GitHubDeploy stack from your laptop so the role can run the deploy document (`ssm:SendCommand` on `smart-tutor-on-premise-deploy` only, plus reading the command's status):
        ```powershell
        Push-Location infra
        npx aws-cdk@latest deploy SmartTutor-OnPremise-prod-GitHubDeploy --require-approval broadening -c smart-tutor:mode=on-premise
        $RoleArn = aws cloudformation describe-stacks --stack-name SmartTutor-OnPremise-prod-GitHubDeploy --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text
        Pop-Location
        ```
     2. Create the GitHub environment `on-premise`, limited to `main`, with its variables:
        ```powershell
        $Repo = "konica/agent-tutor"
        gh api -X PUT "repos/$Repo/environments/on-premise" -F "deployment_branch_policy[protected_branches]=false" -F "deployment_branch_policy[custom_branch_policies]=true" | Out-Null
        gh api -X POST "repos/$Repo/environments/on-premise/deployment-branch-policies" -f name=main -f type=branch | Out-Null
        gh variable set AWS_ROLE_ARN --env on-premise --repo $Repo --body $RoleArn
        gh variable set AWS_REGION --env on-premise --repo $Repo --body us-east-1
        ```
        The role trusts only jobs in this environment (subject `…:environment:on-premise`), and the environment accepts only `main`, so a pull request can't deploy.
   - **Deploy again by hand:** Actions → **deploy** → *Run workflow* from `main`, mode `on-premise`. It runs the same checks, images, and deploy for the head of `main`.
   - **Roll back:** Actions → **rollback** → *Run workflow* from `main`, mode `on-premise`, `image_tag` = the full SHA to go back to. It skips CDK and the build; the VM keeps the deploy files of the last `cdk deploy`. Migrations don't run backwards (see section 6, "To roll back").
   - **When it fails:** the step "Deploy the images on the VM (SSM Run Command)" prints `deploy.sh`'s output; the Troubleshooting table applies. "is not Online in SSM after 10 minutes": the instance is still booting or was replaced; see `/var/log/cloud-init-output.log` through Session Manager.
   - **Every merge can replace the VM:** the AMI is the latest Amazon Linux 2023, read at each `cdk deploy`; after Amazon publishes a new image, the next merge replaces the instance (section 7, "Replace the instance"). The deploy waits for it, and the data survives; expect a few more minutes of downtime.
4. The old §3 heading becomes `## 4. Deploy an image tag by hand` with a first sentence: "Use this when GitHub Actions can't deploy (for example before the one-time setup), or to deploy a commit outside `main`'s head." Add at its end a subsection `### Build images by hand` with these commands (they match `build-images.yml`):
   ```powershell
   git switch --detach $Tag
   $Registry = "$(aws sts get-caller-identity --query Account --output text).dkr.ecr.$env:AWS_REGION.amazonaws.com"
   aws ecr get-login-password | docker login --username AWS --password-stdin $Registry
   $P = "--platform", "linux/amd64"    # the VM is x86_64
   docker build @P --target api    -t "$Registry/smart-tutor/api:$Tag" backend
   docker build @P --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$Registry/smart-tutor/web:$Tag" web
   docker build @P -t "$Registry/smart-tutor/keycloak:$Tag" deploy/keycloak
   docker build @P --target agent  -t "$Registry/smart-tutor/agent:$Tag" backend
   docker build @P --target mcp    -t "$Registry/smart-tutor/mcp:$Tag" backend
   docker build @P --target worker -t "$Registry/smart-tutor/worker:$Tag" backend
   foreach ($Repo in "api", "web", "keycloak", "agent", "mcp", "worker") { docker push "$Registry/smart-tutor/${Repo}:$Tag" }
   git switch -
   ```
5. "Redeploy" section: start with "A merge to `main` redeploys on its own (section 3). By hand:" and keep the bullets.

- [ ] **Step 3: `README.md`** — after the "Local development" section (before "Architecture rules"), add:

```markdown
## Deploy

**On-premise (default).** Every merge to `main` runs the checks, builds the images to ECR, and deploys them to the on-premise VM (`cdk deploy`, then SSM Run Command, then a smoke test): `.github/workflows/deploy.yml`. Setup, a deploy by hand, rollback, and operations: [`docs/runbooks/on-premise-deploy.md`](docs/runbooks/on-premise-deploy.md); backups and monitoring: `on-premise-backups.md`, `on-premise-monitoring.md`.

**Native-cloud (optional).** EKS, RDS, and CloudFront. It deploys only when you run **deploy** by hand with mode `native-cloud`, or on every merge while the repository variable `NATIVE_CLOUD_AUTO_DEPLOY` is `true`: [`docs/runbooks/pilot-deploy.md`](docs/runbooks/pilot-deploy.md), teardown in `pilot-teardown.md`.
```

Also in the Layout table's `docs/` row, change "The AWS pilot's [solution architecture]…" to "The native-cloud pilot's [solution architecture]…, and [runbooks](docs/runbooks/) for engineers (on-premise deploy first; native-cloud deploy, environment overview, AWS prerequisites)".

- [ ] **Step 4: Native-cloud runbooks**

- `pilot-deploy.md`: at the top (after the title), add a note: "**Optional mode.** On-premise is the default and deploys on every merge (`on-premise-deploy.md`). Native-cloud deploys only when chosen (#150)." In the deploy-on-merge section (around line 258, "**What runs.**"), rewrite it to: native-cloud deploys when someone runs **deploy** by hand with mode `native-cloud`, or on every push while `NATIVE_CLOUD_AUTO_DEPLOY` is `true` (unset is off). `deploy.yml` runs the checks, `build-images.yml` builds the six images (skipped when they exist), then `deploy-native-cloud.yml` in the GitHub environment `native-cloud`: `cdk deploy --all`, the add-ons, `helm upgrade --install smart-tutor`, the in-cluster check, the smoke test. One native-cloud deployment at a time (group `deploy-native-cloud`). Rollback: **rollback** with mode `native-cloud`. Replace every other `deploy-pilot.yml` with `deploy-native-cloud.yml` and the environment name `pilot` with `native-cloud` in that file.
- `pilot-aws-prerequisites.md` (and comments/strings in `pilot-aws-prerequisites.ps1` if they name `pilot` as the environment): the environment is `native-cloud` (from `infra/cdk.json`, `smart-tutor:github-environment`); the example subject becomes `…:environment:native-cloud`; section 4's heading "Creates the GitHub environment `native-cloud`". Add a short "Moving from `pilot` (#150)" paragraph: run the script again — it redeploys `SmartTutor-prod-GitHubDeploy` (the role now trusts `native-cloud`) and creates the `native-cloud` environment with the variables; then delete the old environment: `gh api -X DELETE repos/konica/agent-tutor/environments/pilot`. Until then, a native-cloud deploy fails at sign-in.
- `pilot-teardown.md`: the "Kept" row names the GitHub environment `native-cloud`; the step that sets `NATIVE_CLOUD_AUTO_DEPLOY=false` becomes: "Since #150 native-cloud deploys on a merge only while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`. Make sure it isn't: `gh variable delete NATIVE_CLOUD_AUTO_DEPLOY --repo konica/agent-tutor` (or set it to `false`)." Redeploy steps: "Run **deploy** by hand with mode `native-cloud`, or set `NATIVE_CLOUD_AUTO_DEPLOY` to `true` and merge; it needs the kept `GitHubDeploy` role, the bootstrap, and the `native-cloud` environment."
- `pilot-teardown.ps1`: the preflight stops only when the variable is `true`:
  ```powershell
    # Since #150 deploy.yml deploys native-cloud on a merge only while NATIVE_CLOUD_AUTO_DEPLOY is `true`. The script
    # never changes it: that is a repository setting, so you do it.
    $AutoDeploy = gh variable get NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo 2>$null
    if ($AutoDeploy -eq "true") {
        $SetCommand = "gh variable delete NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo"
        if ($DryRun) {
            Write-Warning "NATIVE_CLOUD_AUTO_DEPLOY is 'true'; a real run would stop. Run first: $SetCommand"
        } else {
            throw "NATIVE_CLOUD_AUTO_DEPLOY is 'true', so the next merge to main would redeploy the pilot. Run: $SetCommand"
        }
    }
  ```
  Update the script's header comment (lines ~7 and ~23) to match, and `# same as .github/workflows/deploy-pilot.yml` → `# same as .github/workflows/deploy-native-cloud.yml`.
- `pilot-environment-overview.md`: replace `deploy-pilot.yml` with `deploy-native-cloud.yml`, the environment `pilot` with `native-cloud`, and add `build-images.yml` to the list of files in §4 with "(builds the images; since #150 native-cloud deploys only when chosen)".
- `docs/architecture/solution-architecture.md`: same three replacements in lines ~209-293 and ~417 (file names, environment `native-cloud`, concurrency group `deploy-native-cloud`), and in row "2. Merge to `main`": "`deploy.yml` starts on every push to `main`. It runs the CI checks again, builds the images, deploys on-premise, and calls `deploy-native-cloud.yml` only when chosen (by hand, or while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`; #150)." Don't rewrite the rest of the document.

- [ ] **Step 5: Run the whole infra suite**

Run: `cd infra && uv run pytest -q` and `grep -rn "deploy-pilot\|environment \`pilot\`" README.md docs/ .github/` (expect no output).
Expected: PASS; no stale references.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/ infra/tests/test_workflows.py
git commit -m "Lead the deploy docs with on-premise; native-cloud is optional (#150)

Merges deploy on-premise now, so the runbooks show the one-time GitHub environment setup, the
automatic deploy, rollback by mode, and a by-hand image build for commits that have none."
```
