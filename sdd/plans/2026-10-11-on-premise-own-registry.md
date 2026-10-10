# On-premise Gets Its Own Image Registry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each deployment mode pushes to, pulls from, and is allowed only its own ECR repositories: on-premise `smart-tutor-on-premise/<service>`, native-cloud `smart-tutor/<service>` (ticket #206).

**Architecture:** `ModeNames` gains `repository_prefix` (= the mode's data prefix) and `repository(service)`. `RegistryStack` takes `names`, so both modes build one; on-premise's app adds `SmartTutor-OnPremise-prod-Registry`. The deploy role, the Host's pull permission, the Host's SSM settings, Compose, and every workflow derive repository names from the mode. The image build job deploys its mode's `GitHubDeploy` and `Registry` stacks (CDK, `--exclusively`) before pushing, so the first merge after this change creates the on-premise repositories and widens the role's push permission before the push; no manual one-time step is needed.

**Tech Stack:** AWS CDK (Python), GitHub Actions YAML, bash (deploy.sh), Docker Compose, pytest; Markdown docs.

**Spec:** GitHub issue #206 (parent #145); PRD §9.12 and Appendix A; ADR 0012.

## Global Constraints

- On-premise repositories: exactly `smart-tutor-on-premise/<service>` for `api`, `web`, `keycloak`, `agent`, `mcp`, `worker`.
- Native-cloud repositories keep `smart-tutor/<service>`; its Helm values do not change.
- Both registries: scan on push, lifecycle `max_image_count=30`, `RemovalPolicy.DESTROY`, `empty_on_delete=True`.
- No on-premise template, deploy file, or workflow step for on-premise names a `smart-tutor/<service>` repository.
- Native-cloud deploy role pushes only to `repository/smart-tutor/*`; on-premise's only to `repository/smart-tutor-on-premise/*`.
- The GitHub OIDC provider stays owned by native-cloud's `GitHubDeploy`; on-premise keeps importing it. It is the one accepted shared resource besides the account's CDK bootstrap.
- A deploy or rollback never falls back to the other mode's repositories.
- CDK CLI pinned as in the other workflows: `npx --yes aws-cdk@2.1145.0`.
- Workflows: actions pinned by SHA; `setup-*` before `configure-aws-credentials`; no `${{ inputs.* }}` inside `run:`.
- PRD bumps to v2.36 with a "Changes from v2.35" row. New ADR is `0015`.
- Run from `infra/`: `uv run pytest` (Windows Git Bash: also fine).

## Review Focus

1. **First merge after this change** (on-premise role still has the old push permission, on-premise repositories don't exist): the build must create both before pushing. Pinned by the build-images test that the CDK step names `$STACK_PREFIX-GitHubDeploy` and `$STACK_PREFIX-Registry`, runs `--exclusively`, and comes before `docker login`/`docker push` (Task 4).
2. **Rollback to a commit built before the switch:** its images exist only in `smart-tutor/*`; the on-premise image check must fail with a message pointing at the rebuild steps, not pull from native-cloud. Pinned by a test on the error text and on `$REPOSITORY_PREFIX` in the check (Task 4); documented in Task 5.
3. **A push with `NATIVE_CLOUD_AUTO_DEPLOY=true`:** both modes must get images, each built by its own role. Pinned by the deploy.yml test that each deploy job needs its own images job with the same `if` (Task 4).
4. **An unknown mode passed to build-images:** must fail, not default to on-premise's repositories. Pinned by a test that the mapping step has an error arm (Task 4).
5. **The VM between the CDK deploy and the SSM deploy** (old env file, new bundle not yet unpacked): Compose and its env file change together, because the SSM document unpacks the bundle and deploy.sh re-renders the env file in one run. Pinned by the Host test that deploy.sh writes `REPOSITORY_PREFIX` from `host/repository-prefix` and compose requires `${REPOSITORY_PREFIX:?}` (Task 3).

---

## File Structure

| File | Change |
|---|---|
| `infra/smart_tutor_infra/names.py` | `repository_prefix`, `repository(service)`; module docstring no longer says ECR is shared |
| `infra/smart_tutor_infra/stacks/registry.py` | `RegistryStack(names=...)` names repositories via `names.repository` |
| `infra/smart_tutor_infra/app_stacks.py` | on-premise builds `<prefix>-Registry`; native-cloud passes `names` |
| `infra/smart_tutor_infra/stacks/github_deploy.py` | push resource `repository/{names.repository_prefix}/*` |
| `infra/smart_tutor_infra/stacks/host.py` | pull from `names.repository(s)`; SSM `host/repository-prefix` |
| `deploy/on-premise/compose.yaml`, `deploy/on-premise/deploy.sh` | images `${REGISTRY:?}/${REPOSITORY_PREFIX:?}/<svc>`; deploy.sh renders `REPOSITORY_PREFIX` |
| `.github/workflows/build-images.yml`, `deploy.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`, `rollback.yml` | per-mode repositories; one images job per mode; CDK registry step |
| `infra/tests/test_synth.py`, `test_deployment_modes.py`, `test_host.py`, `test_workflows.py` | tests |
| `docs/runbooks/*.md`, `docs/runbooks/pilot-teardown.ps1`, `docs/architecture/solution-architecture.md`, `README.md` | docs; teardown now destroys native-cloud's Registry |
| `sdd/adr/0015-deployment-modes-share-no-stack.md`, `sdd/adr/0012-...md`, `sdd/adr/README.md`, `sdd/prd.md`, `CONTEXT.md`, `sdd/specs/2026-10-02-project-structure-design.md` | decision records |

---

### Task 1: Each mode has a Registry stack named after its data prefix

**Files:**
- Modify: `infra/smart_tutor_infra/names.py`
- Modify: `infra/smart_tutor_infra/stacks/registry.py`
- Modify: `infra/smart_tutor_infra/app_stacks.py`
- Test: `infra/tests/test_synth.py:110-118`, `infra/tests/test_deployment_modes.py`

**Interfaces:**
- Produces: `ModeNames.repository_prefix -> str` (property, = `data_prefix`); `ModeNames.repository(service: str) -> str` (= `f"{data_prefix}/{service}"`); `RegistryStack(scope, id, *, names: ModeNames, services=SERVICES, **kwargs)` with `.repositories: dict[str, ecr.Repository]` and output `RegistryUri`. `SERVICES` stays in `stacks/registry.py`.

- [ ] **Step 1: Write the failing tests**

In `infra/tests/test_deployment_modes.py`, add `"Registry"` to `ON_PREMISE_STACKS`:

```python
ON_PREMISE_STACKS = {
    f"SmartTutor-OnPremise-prod-{s}" for s in ("Storage", "Config", "Budgets", "GitHubDeploy", "Registry", "Host")
}
```

Replace `test_on_premise_references_the_shared_registry_instead_of_creating_one` with:

```python
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
        assert not re.search(r"smart-tutor/(api|web|keycloak|agent|mcp|worker)\b", json.dumps(Template.from_stack(stack).to_json())), stack.stack_name
```

In `infra/tests/test_synth.py`, extend `test_registry_has_one_repository_per_service_and_empties_them_on_delete` (native-cloud default app) with the same lifecycle and deletion checks so both modes are pinned identically:

```python
    for repo in repos.values():
        assert repo["DeletionPolicy"] == "Delete"
        assert '"countNumber":30' in repo["Properties"]["LifecyclePolicy"]["LifecyclePolicyText"]
```

(Check `make_app()`'s default mode in `test_synth.py`; that test already synthesizes native-cloud's `Registry`. If the lifecycle text in the template has spaces, match it with `json.loads(...)["rules"][0]["selection"]["countNumber"] == 30` instead.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd infra && uv run pytest tests/test_deployment_modes.py tests/test_synth.py -q`
Expected: FAIL (`repository` attribute missing; no on-premise Registry stack).

- [ ] **Step 3: Implement**

`names.py` — module docstring's last sentences become: "Each mode has its own stacks, bucket, queues, SSM parameters, secrets, deploy role, and ECR repositories (#206). Native-cloud keeps the names the pilot was deployed with." Add to `ModeNames` after `secret_prefix`:

```python
    @property
    def repository_prefix(self) -> str:
        """ECR repositories `<repository_prefix>/<service>` (RegistryStack, #206)."""
        return self.data_prefix

    def repository(self, service: str) -> str:
        return f"{self.repository_prefix}/{service}"
```

Also update the `data_prefix` field comment to: `# the bucket, queues, SSM path, secrets, deploy role, and ECR repositories`.

`registry.py`:

```python
"""ECR repositories `<repository prefix>/<service>` of one deployment mode (#56, #206): `smart-tutor/<service>` for
native-cloud, `smart-tutor-on-premise/<service>` for on-premise. Each mode's deploy role may push only to its own."""

from collections.abc import Sequence
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from constructs import Construct

from smart_tutor_infra.names import ModeNames

SERVICES = ("api", "web", "keycloak", "agent", "mcp", "worker")


class RegistryStack(cdk.Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        names: ModeNames,
        services: Sequence[str] = SERVICES,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        # Images are rebuilt from git, so a teardown deletes them; a kept repository would block the next deploy.
        self.repositories = {
            service: ecr.Repository(
                self,
                f"{service.capitalize()}Repository",
                repository_name=names.repository(service),
                image_scan_on_push=True,
                lifecycle_rules=[ecr.LifecycleRule(max_image_count=30)],
                removal_policy=cdk.RemovalPolicy.DESTROY,
                empty_on_delete=True,
            )
            for service in services
        }
        cdk.CfnOutput(self, "RegistryUri", value=f"{self.account}.dkr.ecr.{self.region}.amazonaws.com")
```

`app_stacks.py` — `_on_premise` docstring: `"""Storage, Config, Budgets, GitHubDeploy, and Registry of its own, and the Host; it shares no stack with native-cloud
(ADR 0015). The Host names its repositories through ModeNames, so it never references the Registry stack."""`. Add `RegistryStack(app, f"{prefix}-Registry", env=env, names=names),` to the returned list right after `deploy`. In `_native_cloud`, change to `RegistryStack(app, f"{prefix}-Registry", env=env, names=names)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd infra && uv run pytest tests/test_deployment_modes.py tests/test_synth.py -q`
Expected: PASS except `test_no_on_premise_template_names_a_native_cloud_repository`, which still fails on the Host (fixed in Task 3). Mark it `@pytest.mark.xfail(strict=True, reason="Host still pulls smart-tutor/*; Task 3")` for now — Task 3 removes the marker.

- [ ] **Step 5: Commit**

```bash
git add infra/smart_tutor_infra infra/tests
git commit -m "Give on-premise a Registry stack of its own (#206)"
```

---

### Task 2: Each deploy role pushes only to its mode's repositories

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/github_deploy.py`
- Test: `infra/tests/test_synth.py` (native-cloud GitHubDeploy), `infra/tests/test_deployment_modes.py` (on-premise GitHubDeploy)

**Interfaces:**
- Consumes: `ModeNames.repository_prefix` (Task 1).

- [ ] **Step 1: Write the failing tests**

In `test_synth.py`, add to `test_deploy_role_gets_only_the_deployment_permissions`:

```python
    push = next(s for s in statements if s["Sid"] == "EcrPushAppImages")
    assert json.dumps(push["Resource"]).endswith('repository/smart-tutor/*"]}')
```

(Inspect the rendered `Resource` shape first: it is an `Fn::Join` of `arn:aws:ecr:`, region, account, and `:repository/smart-tutor/*`. Assert on `json.dumps(push["Resource"])` containing `":repository/smart-tutor/*"`.)

In `test_deployment_modes.py`, add:

```python
def test_on_premise_deploy_role_pushes_only_to_its_own_repositories() -> None:
    (policy,) = on_premise("GitHubDeploy").find_resources("AWS::IAM::Policy").values()
    push = next(s for s in policy["Properties"]["PolicyDocument"]["Statement"] if s["Sid"] == "EcrPushAppImages")
    resource = json.dumps(push["Resource"])
    assert ":repository/smart-tutor-on-premise/*" in resource
    assert ":repository/smart-tutor/*" not in resource
```

- [ ] **Step 2: Run to verify the on-premise test fails**

Run: `cd infra && uv run pytest tests/test_deployment_modes.py -q -k pushes_only`
Expected: FAIL (resource is `repository/smart-tutor/*`).

- [ ] **Step 3: Implement**

In `github_deploy.py`, `EcrPushAppImages` resource becomes `f"arn:aws:ecr:{region}:{account}:repository/{names.repository_prefix}/*"`. Class docstring: replace "push app images to the shared `smart-tutor/*` ECR repositories" with "push app images to its mode's ECR repositories (`<repository prefix>/*`, #206)". Module docstring: append "The account's GitHub OIDC provider is the one resource the modes share (ADR 0015): AWS allows one per URL, so native-cloud's copy creates it and on-premise's imports it."

- [ ] **Step 4: Run tests**

Run: `cd infra && uv run pytest tests/test_deployment_modes.py tests/test_synth.py -q`
Expected: PASS (the xfail from Task 1 still xfails).

- [ ] **Step 5: Commit**

```bash
git add infra
git commit -m "Limit each deploy role's image push to its mode's repositories (#206)"
```

---

### Task 3: The Host pulls only from on-premise's repositories

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/host.py` (docstring line 29; `self.repositories` ~108; SSM settings loop ~313)
- Modify: `deploy/on-premise/compose.yaml` (7 `image:` lines), `deploy/on-premise/deploy.sh` (settings, env file, pull message)
- Test: `infra/tests/test_host.py`, `infra/tests/test_deployment_modes.py` (remove the xfail)

**Interfaces:**
- Consumes: `ModeNames.repository(service)`, `ModeNames.repository_prefix` (Task 1).
- Produces: SSM parameter `/<data prefix>/host/repository-prefix` = `smart-tutor-on-premise`; env-file key `REPOSITORY_PREFIX`.

- [ ] **Step 1: Write the failing tests**

In `test_host.py`, in `test_instance_role_pulls_images_...`, replace the `pull` assertion with:

```python
    pull = json.dumps(statements["EcrPullAppImages"]["Resource"])
    assert all(
        f"repository/smart-tutor-on-premise/{s}" in pull for s in ("api", "web", "keycloak", "agent", "mcp", "worker")
    )
    assert "repository/smart-tutor/" not in pull  # never native-cloud's registry (#206)
```

In `test_deploy_settings_name_on_premise_resources`, add:

```python
    assert _parameter(t, "repository-prefix") == "smart-tutor-on-premise"
```

Replace `test_app_images_come_from_ecr_by_commit_tag` with:

```python
def test_app_images_come_from_the_on_premise_registry_by_commit_tag(compose: dict[str, Any]) -> None:
    images = {"keycloak": "keycloak", "api": "api", "migrate": "api", "web": "web", "agent": "agent", "mcp": "mcp"}
    for name, repo in {**images, "worker": "worker"}.items():
        assert compose["services"][name]["image"] == f"${{REGISTRY:?}}/${{REPOSITORY_PREFIX:?}}/{repo}:${{IMAGE_TAG:?}}"
    assert "/smart-tutor/" not in (ON_PREMISE_DIR / "compose.yaml").read_text(encoding="utf-8").split("services:")[1]


def test_deploy_script_renders_the_repository_prefix_from_the_host_settings() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert "repository_prefix=$(param host/repository-prefix)" in script
    assert "\nREPOSITORY_PREFIX=$repository_prefix\n" in script
    # read before the env file is written, so a failed read stops the deploy before anything changes
    assert script.index("param host/repository-prefix") < script.index('cat > "$rendered"')
```

(Check the `split("services:")` guard: the header comment of compose.yaml mentions `/opt/smart-tutor/` and `/etc/smart-tutor/` paths, which contain `/smart-tutor/`; if `services:` text also appears in the header, instead assert with a regex `not re.search(r"/smart-tutor/(api|web|keycloak|agent|mcp|worker):", text)`. Prefer the regex.)

In `test_deployment_modes.py`, remove the `xfail` marker from `test_no_on_premise_template_names_a_native_cloud_repository`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra && uv run pytest tests/test_host.py tests/test_deployment_modes.py -q`
Expected: FAIL on the pull resource, the parameter, compose images, deploy.sh, and the no-native-cloud-repository test.

- [ ] **Step 3: Implement**

`host.py`:
- Docstring line 29 → `ECR is on-premise's own RegistryStack (#206); the Host names its repositories through ModeNames instead of referencing that stack, so either can be destroyed on its own.`
- `self.repositories` → `ecr.Repository.from_repository_name(self, f"{service.capitalize()}Repository", names.repository(service))`.
- In the settings loop, after `("registry", ...)`, add `("repository-prefix", names.repository_prefix),`.

`compose.yaml`: every `image: ${REGISTRY:?}/smart-tutor/<svc>:${IMAGE_TAG:?}` → `image: ${REGISTRY:?}/${REPOSITORY_PREFIX:?}/<svc>:${IMAGE_TAG:?}` (7 lines: keycloak, api, migrate (api), agent, mcp, worker, web). Header comment line 4 "Our images come from ECR by commit tag." → "Our images come from on-premise's ECR repositories (`smart-tutor-on-premise/<service>`) by commit tag."

`deploy.sh`:
- after `registry=$(param host/registry)` add `repository_prefix=$(param host/repository-prefix)`.
- in the heredoc after `REGISTRY=$registry` add `REPOSITORY_PREFIX=$repository_prefix`.
- `echo "Pulling $tag from $registry"` → `echo "Pulling $tag from $registry/$repository_prefix"`.

- [ ] **Step 4: Run the infra suite**

Run: `cd infra && uv run pytest -q`
Expected: all PASS except `test_workflows.py` (unchanged so far, should still pass) — the whole suite must be green.

- [ ] **Step 5: Commit**

```bash
git add infra deploy/on-premise
git commit -m "Pull on-premise images from smart-tutor-on-premise/* (#206)"
```

---

### Task 4: Workflows build, check, and deploy each mode from its own repositories

**Files:**
- Modify: `.github/workflows/build-images.yml`, `.github/workflows/deploy.yml`, `.github/workflows/deploy-on-premise.yml`, `.github/workflows/deploy-native-cloud.yml`, `.github/workflows/rollback.yml` (comment and input description only)
- Test: `infra/tests/test_workflows.py`

**Interfaces:**
- Consumes: `mode_names(mode).stack_prefix`, `.repository_prefix`, `MODES` from `smart_tutor_infra.names`.
- Produces: in build-images, env `STACK_PREFIX`, `REPOSITORY_PREFIX`, `REGISTRY` (via `$GITHUB_ENV`); in deploy-on-premise / deploy-native-cloud, job-level env `REPOSITORY_PREFIX`.

- [ ] **Step 1: Write the failing tests**

In `test_workflows.py`, add the import `from smart_tutor_infra.names import MODES, NATIVE_CLOUD, ON_PREMISE, mode_names`.

Update `test_only_main_and_rollback_reach_the_deploy_environments`: `assert callers == 6  # deploy: images per mode, on-premise, native-cloud; rollback: on-premise, native-cloud`.

Replace `test_a_push_checks_builds_then_deploys_on_premise` and `test_native_cloud_deploys_only_when_chosen` with:

```python
ON_PREMISE_IF = "github.event_name == 'push' || inputs.mode == 'on-premise'"
NATIVE_CLOUD_IF = (
    "(github.event_name == 'push' && vars.NATIVE_CLOUD_AUTO_DEPLOY == 'true') || inputs.mode == 'native-cloud'"
)


def test_each_mode_gets_its_images_built_with_its_own_role_before_it_deploys() -> None:
    jobs = workflow("deploy.yml")["jobs"]
    assert jobs["checks"]["uses"] == "./.github/workflows/ci.yml"
    for mode, condition, deploy_workflow in (
        ("on-premise", ON_PREMISE_IF, "deploy-on-premise.yml"),
        ("native-cloud", NATIVE_CLOUD_IF, "deploy-native-cloud.yml"),
    ):
        images = jobs[f"images-{mode}"]
        assert images["needs"] == "checks"
        assert images["uses"] == "./.github/workflows/build-images.yml"
        assert images["with"] == {"image_tag": "${{ github.sha }}", "environment": mode}
        # built exactly when the mode deploys, so its repositories have the images it checks for
        assert images["if"] == condition
        deploy = jobs[mode]
        assert deploy["needs"] == f"images-{mode}"
        assert deploy["if"] == condition
        assert deploy["uses"] == f"./.github/workflows/{deploy_workflow}"
        assert deploy["with"] == {"image_tag": "${{ github.sha }}", "infrastructure": True}
    assert "images" not in jobs
```

Replace `test_images_are_built_for_the_commit_and_pushed` with:

```python
def test_images_are_built_for_the_commit_and_pushed_to_the_modes_repositories() -> None:
    job = images_job()
    text = steps_text(job)
    checkout = next(s for s in job["steps"] if "actions/checkout" in str(s.get("uses")))
    assert checkout["with"]["ref"] == "${{ inputs.image_tag }}"
    for image in IMAGES:
        assert f'"$REGISTRY/$REPOSITORY_PREFIX/{image}:$IMAGE_TAG"' in text, image
    assert "/smart-tutor/" not in text  # no repository is written out; the mode names them
    for target in ("api", "agent", "mcp", "worker"):
        assert f"--target {target}" in text
    assert "VITE_API_URL=/api" in text and "VITE_KEYCLOAK_URL=/auth" in text
    assert "docker push" in text
    assert "aws sts get-caller-identity --query Account" in text
    assert index_of(job, "docker build") < index_of(job, "docker push")


def test_build_maps_each_mode_to_its_stacks_and_repositories() -> None:
    job = images_job()
    assert job["env"]["MODE"] == "${{ inputs.environment }}"
    run = step(job, "Name the mode's stacks and repositories")["run"]
    arms = dict(
        (m, (s, r)) for m, s, r in re.findall(r"^\s*([\w-]+)\) stack_prefix=(\S+) repository_prefix=(\S+) ;;$", run, re.M)
    )
    assert arms == {m: (mode_names(m).stack_prefix, mode_names(m).repository_prefix) for m in MODES}
    # an unknown mode fails instead of falling back to one mode's repositories
    assert re.search(r"^\s*\*\) .*::error::.*exit 1", run, re.M)
    assert index_of(job, "stack_prefix=") < index_of(job, "describe-images")


def test_build_creates_the_modes_registry_and_push_permission_before_pushing() -> None:
    # The first merge after #206 builds with a role that can't push to smart-tutor-on-premise/* yet, into repositories
    # that don't exist yet: the build deploys both stacks first (a no-op once they are current).
    job = images_job()
    cdk = step(job, "Deploy the deploy role and the registry (CDK)")
    assert cdk["if"] == "steps.existing.outputs.all != 'true'"
    assert cdk["working-directory"] == "infra"
    assert "uv sync --frozen" in cdk["run"]
    assert (
        'npx --yes aws-cdk@2.1145.0 deploy --exclusively "$STACK_PREFIX-GitHubDeploy" "$STACK_PREFIX-Registry"'
        ' --require-approval never -c smart-tutor:mode="$MODE"'
    ) in cdk["run"]
    assert index_of(job, "describe-images") < job["steps"].index(cdk) < index_of(job, "docker login")
    assert job["env"]["JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION"] == "1"
    assert any("setup-node" in str(s.get("uses")) for s in job["steps"])
    assert any("setup-uv" in str(s.get("uses")) for s in job["steps"])


def test_deploys_check_their_own_modes_repositories() -> None:
    for job, mode in ((on_premise_job(), ON_PREMISE), (native_cloud_job(), NATIVE_CLOUD)):
        assert job["env"]["REPOSITORY_PREFIX"] == mode_names(mode).repository_prefix, mode
        check = step(job, "Check the images exist")["run"]
        assert '--repository-name "$REPOSITORY_PREFIX/$repo"' in check, mode
        assert "smart-tutor/$repo" not in check, mode


def test_on_premise_explains_a_rollback_to_a_commit_from_before_its_own_registry() -> None:
    check = step(on_premise_job(), "Check the images exist")["run"]
    # images of commits merged before #206 are only in native-cloud's smart-tutor/*; the check never pulls them
    assert "before #206" in check and "on-premise-deploy.md" in check
```

In `test_images_are_built_only_when_missing`, keep as is; additionally it must hold for the CDK step (covered above).

- [ ] **Step 2: Run to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: FAIL on the new tests and the caller count.

- [ ] **Step 3: Implement `build-images.yml`**

```yaml
# Builds the six app images for one commit and pushes them to the ECR repositories of one deployment mode, tagged with
# the full commit SHA (#150, #206): on-premise `smart-tutor-on-premise/<service>`, native-cloud `smart-tutor/<service>`.
# Called by deploy.yml once per mode it deploys, with that mode's deploy role (which may push only to its own
# repositories). Skips the build when all six images are already there; otherwise it first deploys the mode's
# GitHubDeploy and Registry stacks, so the repositories and the role's push permission exist before the push (the
# first merge after #206 needed both; later runs find nothing to change), then rebuilds and pushes all six.
name: build-images

on:
  workflow_call:
    inputs:
      image_tag:
        description: Full commit SHA to build and tag the images with
        type: string
        required: true
      environment:
        description: Deployment mode (and GitHub environment) whose repositories get the images (on-premise or native-cloud)
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
      MODE: ${{ inputs.environment }}
      JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION: "1"
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0
        with:
          ref: ${{ inputs.image_tag }}

      # Setup actions run before the AWS credentials exist in the environment.
      - uses: actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020 # v4.4.0
        with:
          node-version: 22
      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0

      - uses: aws-actions/configure-aws-credentials@7474bc4690e29a8392af63c5b98e7449536d5c3a # v4.3.1
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      # The same names as ModeNames (infra/smart_tutor_infra/names.py); test_workflows.py keeps them in step.
      - name: Name the mode's stacks and repositories
        run: |
          case "$MODE" in
            on-premise) stack_prefix=SmartTutor-OnPremise-prod repository_prefix=smart-tutor-on-premise ;;
            native-cloud) stack_prefix=SmartTutor-prod repository_prefix=smart-tutor ;;
            *) echo "::error::Unknown deployment mode $MODE (on-premise or native-cloud)"; exit 1 ;;
          esac
          account=$(aws sts get-caller-identity --query Account --output text)
          {
            echo "STACK_PREFIX=$stack_prefix"
            echo "REPOSITORY_PREFIX=$repository_prefix"
            echo "REGISTRY=$account.dkr.ecr.$AWS_REGION.amazonaws.com"
          } >> "$GITHUB_ENV"

      # A repository that doesn't exist yet counts as missing images.
      - name: Check which images exist
        id: existing
        run: |
          all=true
          for repo in api web keycloak agent mcp worker; do
            if aws ecr describe-images --repository-name "$REPOSITORY_PREFIX/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null 2>&1; then
              echo "$REPOSITORY_PREFIX/$repo:$IMAGE_TAG is already in ECR"
            else
              all=false
            fi
          done
          echo "all=$all" >> "$GITHUB_OUTPUT"

      # --exclusively: only these two stacks, not Network (native-cloud) or the rest of the mode; deploy.yml's deploy
      # job runs the full cdk deploy afterwards.
      - name: Deploy the deploy role and the registry (CDK)
        if: steps.existing.outputs.all != 'true'
        working-directory: infra
        run: |
          uv sync --frozen
          npx --yes aws-cdk@2.1145.0 deploy --exclusively "$STACK_PREFIX-GitHubDeploy" "$STACK_PREFIX-Registry" --require-approval never -c smart-tutor:mode="$MODE"

      - name: Sign in to ECR
        if: steps.existing.outputs.all != 'true'
        run: aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"

      - name: Build the images
        if: steps.existing.outputs.all != 'true'
        run: |
          docker build --target api -t "$REGISTRY/$REPOSITORY_PREFIX/api:$IMAGE_TAG" backend
          docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$REGISTRY/$REPOSITORY_PREFIX/web:$IMAGE_TAG" web
          docker build -t "$REGISTRY/$REPOSITORY_PREFIX/keycloak:$IMAGE_TAG" deploy/keycloak
          docker build --target agent -t "$REGISTRY/$REPOSITORY_PREFIX/agent:$IMAGE_TAG" backend
          docker build --target mcp -t "$REGISTRY/$REPOSITORY_PREFIX/mcp:$IMAGE_TAG" backend
          docker build --target worker -t "$REGISTRY/$REPOSITORY_PREFIX/worker:$IMAGE_TAG" backend

      - name: Push the images
        if: steps.existing.outputs.all != 'true'
        run: |
          for repo in api web keycloak agent mcp worker; do docker push "$REGISTRY/$REPOSITORY_PREFIX/$repo:$IMAGE_TAG"; done
```

- [ ] **Step 4: Implement `deploy.yml`**

Header comment: replace line 1 with `# Every push to main: the CI checks, then per deployed mode its images (built into that mode's own repositories, #206)
# and its deploy. On-premise deploys on every push (PRD §9.12, ADR 0012, #150).` Keep the other header lines. Replace the `images` job with two jobs and change `needs` of the deploy jobs:

```yaml
  # Each mode's images go to its own repositories with its own deploy role (#206), so a push that deploys both modes
  # builds twice.
  images-on-premise:
    needs: checks
    if: github.event_name == 'push' || inputs.mode == 'on-premise'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `on-premise` environment
    uses: ./.github/workflows/build-images.yml
    with:
      image_tag: ${{ github.sha }}
      environment: on-premise

  images-native-cloud:
    needs: checks
    if: (github.event_name == 'push' && vars.NATIVE_CLOUD_AUTO_DEPLOY == 'true') || inputs.mode == 'native-cloud'
    permissions:
      contents: read
      id-token: write  # OIDC sign-in to AWS, used only inside the `native-cloud` environment
    uses: ./.github/workflows/build-images.yml
    with:
      image_tag: ${{ github.sha }}
      environment: native-cloud
```

`on-premise.needs: images-on-premise`; `native-cloud.needs: images-native-cloud`.

- [ ] **Step 5: Implement `deploy-on-premise.yml` and `deploy-native-cloud.yml`**

`deploy-on-premise.yml`: add to job `env`: `REPOSITORY_PREFIX: smart-tutor-on-premise  # its own ECR repositories (#206); never native-cloud's`. Replace the check step body:

```yaml
      # Images of commits merged before #206 are only in native-cloud's repositories; they are never pulled from there.
      - name: Check the images exist
        run: |
          for repo in api web keycloak agent mcp worker; do
            aws ecr describe-images --repository-name "$REPOSITORY_PREFIX/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null \
              || { echo "::error::$REPOSITORY_PREFIX/$repo:$IMAGE_TAG is not in ECR (it keeps the last 30 images; a commit merged before #206 has none here: build them by hand, docs/runbooks/on-premise-deploy.md)"; exit 1; }
          done
```

`deploy-native-cloud.yml`: add to job `env`: `REPOSITORY_PREFIX: smart-tutor  # its own ECR repositories (#206)`. Check step:

```yaml
      - name: Check the images exist
        run: |
          for repo in api web keycloak agent mcp worker; do
            aws ecr describe-images --repository-name "$REPOSITORY_PREFIX/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null \
              || { echo "::error::$REPOSITORY_PREFIX/$repo:$IMAGE_TAG is not in ECR (it keeps the last 30 images; only commits deployed to native-cloud have images here)"; exit 1; }
          done
```

Header comment line 3 of `deploy-native-cloud.yml`: "deploy.yml builds the images first." → "deploy.yml builds its images into `smart-tutor/*` first."

`rollback.yml`: header comment add "Each mode checks for the images in its own repositories (#206)." and `image_tag` description → `Full commit SHA of an earlier deploy of this mode (its images must still be in the mode's ECR repositories)`.

- [ ] **Step 6: Run the infra suite**

Run: `cd infra && uv run pytest -q`
Expected: PASS. Also sanity-check YAML: `python -c "import yaml,glob;[yaml.safe_load(open(f)) for f in glob.glob('../.github/workflows/*.yml')]"` from `infra` via `uv run`.

- [ ] **Step 7: Commit**

```bash
git add .github/workflows infra/tests/test_workflows.py
git commit -m "Build, check, and deploy each mode from its own repositories (#206)"
```

---

### Task 5: Runbooks, architecture doc, README, and teardown stop calling ECR shared

**Files:**
- Modify: `docs/runbooks/on-premise-deploy.md` (lines ~12, ~24, ~107-153, rollback section), `docs/runbooks/pilot-deploy.md` (~82-91, ~252, ~293), `docs/runbooks/pilot-environment-overview.md` (~27, ~181 and a note), `docs/runbooks/pilot-aws-prerequisites.md` (~21, ~117, ~140), `docs/runbooks/pilot-teardown.md` (section 2 table, ~23, ~64), `docs/runbooks/pilot-teardown.ps1` (synopsis, `$DeleteStacks`, `$KeepStacks`, comment ~239), `docs/architecture/solution-architecture.md` (~281, ~284, ~291, ~417), `README.md` (~132)
- Test: `infra/tests/test_workflows.py` (one runbook test)

- [ ] **Step 1: Write the failing test**

Append to `test_workflows.py`:

```python
def test_runbooks_no_longer_call_ecr_shared_and_explain_old_rollbacks() -> None:
    names = ("on-premise-deploy.md", "pilot-deploy.md", "pilot-environment-overview.md", "pilot-aws-prerequisites.md",
             "pilot-teardown.md", "pilot-teardown.ps1")
    for name in names:
        text = (RUNBOOKS / name).read_text(encoding="utf-8")
        assert not re.search(r"shared with (native-cloud|on-premise)|[Ss]hared ECR|ECR is shared", text), name
    on_premise = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    assert "smart-tutor-on-premise/<service>" in on_premise
    assert "before #206" in on_premise  # what a rollback to an older commit does
    assert '"$Registry/smart-tutor/' not in on_premise  # the hand build pushes to on-premise's repositories
    assert "before #206" in (RUNBOOKS / "pilot-deploy.md").read_text(encoding="utf-8")
    teardown = (RUNBOOKS / "pilot-teardown.ps1").read_text(encoding="utf-8")
    assert '"Registry"' in teardown.split("$DeleteStacks")[1].split("$KeepStacks")[0]
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd infra && uv run pytest tests/test_workflows.py -q -k runbooks_no_longer`
Expected: FAIL.

- [ ] **Step 3: Update the docs** (plain, short sentences in the existing voice; PowerShell commands)

`on-premise-deploy.md`:
- Table row "Images" → `| Images | ECR `smart-tutor-on-premise/<service>:<commit SHA>`, on-premise's own `SmartTutor-OnPremise-prod-Registry` stack (#206) |`.
- Prerequisite bullet (line 24) → the repositories come from `SmartTutor-OnPremise-prod-Registry`; `build-images.yml` deploys that stack (and the deploy role) before its first push, so nothing is deployed by hand for them. Keep the rest; "A commit merged while no images were built" also covers commits merged before #206 (their images are only in native-cloud's `smart-tutor/*`).
- Image check snippet (~112): `--repository-name "smart-tutor-on-premise/$Repo"`.
- "Build images by hand" (~140-153): `$Prefix = "smart-tutor-on-premise"` and every tag `"$Registry/$Prefix/<svc>:$Tag"`; the push loop `docker push "$Registry/$Prefix/${Repo}:$Tag"`. Add before it: "The repositories must exist: if `SmartTutor-OnPremise-prod-Registry` isn't deployed yet, run `npx aws-cdk@2.1145.0 deploy --exclusively SmartTutor-OnPremise-prod-Registry -c smart-tutor:mode=on-premise` from `infra/` first."
- Rollback section: add a paragraph "**Commits from before #206.** Until #206 on-premise used native-cloud's repositories `smart-tutor/*`, so a commit merged before it has no images in `smart-tutor-on-premise/*`. A rollback to it stops at "Check the images exist" with an error that names this section; it never pulls from native-cloud's repositories. To go back to such a commit anyway, build its images by hand (section 4, "Build images by hand", with that commit checked out), then run the rollback. Remember that a rollback keeps the deploy files of the last `cdk deploy`."

`pilot-deploy.md`:
- Before the build commands (~82): note "These push to native-cloud's own repositories `smart-tutor/<service>` (`SmartTutor-prod-Registry`); on-premise has its own since #206."
- Teardown sentence (~252): "(a plain destroy of `Network` would also delete its dependents, the `Registry` among them)" and teardown now deletes the Registry too.
- Rollback (~293): add "It checks native-cloud's repositories only: a commit has images there only if it was deployed to native-cloud (each mode builds into its own repositories since #206; commits merged before #206 were built into `smart-tutor/*` for both modes, so those within the last 30 images are there)."

`pilot-environment-overview.md`: line 27 → `ECR["ECR<br/>smart-tutor/api, web, keycloak, agent, mcp, worker"]`; add after the first diagram one sentence: "ECR here is native-cloud's own registry; on-premise has its own `smart-tutor-on-premise/*` repositories (#206, ADR 0015)."

`pilot-aws-prerequisites.md`:
- Table (~21): `| ECR repositories | Per mode: native-cloud `smart-tutor/<service>`, on-premise `smart-tutor-on-premise/<service>` (`api`, `web`, `keycloak`, `agent`, `mcp`, `worker`) |`.
- Permissions table (~117): `| ECR push and pull actions | its own mode's repositories: `smart-tutor/*` (native-cloud) or `smart-tutor-on-premise/*` (on-premise) | push app images |`.
- Replace the "**Shared ECR repositories.**" paragraph (~140) with "**ECR repositories.** Each mode has its own (`SmartTutor-prod-Registry`, `SmartTutor-OnPremise-prod-Registry`; ADR 0015). The image build deploys its mode's Registry and GitHubDeploy stacks before its first push, so neither needs deploying by hand. The only resource the modes share is the account's GitHub OIDC provider: AWS allows one per URL, so native-cloud's `GitHubDeploy` creates it and on-premise's imports it. Deploy native-cloud's `GitHubDeploy` first on a fresh account (section above)." (Verify the section reference matches the file's actual structure.)

`pilot-teardown.md`: table: move `Registry` into the Deleted row ("`Storage`, `Edge`, `Data`, `Cluster`, `Config`, `Registry`, `Network`") and delete the "Kept | Registry" row; line 23: "...would also destroy every stack that depends on it."; line 64: drop "ECR images in `Registry`,". Add to section 8 (redeploy) or the "kept" text: "A redeploy recreates the repositories: the image build deploys `Registry` before it pushes." Check section 8 and adjust any sentence that assumed images survive (rollback after a redeploy starts fresh).

`pilot-teardown.ps1`: synopsis step 4 list adds `Registry` before `Network`; "Kept on purpose" drops the Registry clause; `$DeleteStacks = @("Storage", "Edge", "Data", "Cluster", "Config", "Registry") + @(if ($DeleteBudget) { "Budgets" }) + @("Network")`; `$KeepStacks = @("SmartTutor-prod-GitHubDeploy", "CDKToolkit") + ...`; the comment at ~239 → "a destroy of Network would also destroy every stack that depends on it." Search the script for any other `Registry` mention and keep it consistent.

`solution-architecture.md`: line 281 role permissions "push to the `smart-tutor/*` ECR repositories" stays correct for native-cloud — leave it. Line 284: "pushed to ECR (`smart-tutor/<name>`)" → "pushed to native-cloud's ECR repositories (`smart-tutor/<name>`; on-premise builds into its own `smart-tutor-on-premise/<name>`, #206). Before building, the job deploys the `GitHubDeploy` and `Registry` stacks so the repositories exist." Line 291 rollback: add "only commits deployed to native-cloud have images in its repositories." Line 417 already says teardown deletes the repositories: now true, leave.

`README.md` line 132: "builds the images to ECR" → "builds the images into on-premise's own ECR repositories".

- [ ] **Step 4: Run tests**

Run: `cd infra && uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs README.md infra/tests/test_workflows.py
git commit -m "Describe a registry per mode in the runbooks; teardown deletes native-cloud's (#206)"
```

---

### Task 6: ADR 0015, PRD v2.36, CONTEXT.md, and the structure spec

**Files:**
- Create: `sdd/adr/0015-deployment-modes-share-no-stack.md`
- Modify: `sdd/adr/0012-on-premise-default-deployment-mode.md` (status line + the "ECR is shared" sentence), `sdd/adr/README.md`, `sdd/prd.md` (status line v2.35→v2.36, new "Changes from v2.35" row, Appendix A lines ~516, ~525, ~527, §9.12 delivery ~535, ~792), `CONTEXT.md` (On-premise mode / Deployment mode), `sdd/specs/2026-10-02-project-structure-design.md:178`, `AGENTS.md` (ADR range `0001–0014` → `0001–0015`, PRD version `v2.35` → `v2.36`)

- [ ] **Step 1: Write ADR 0015**

```markdown
# 0015. Deployment modes share no stack

- Status: accepted
- Date: 2026-10-11
- Supersedes: ADR 0012's "ECR is shared"

## Context

ADR 0012 gave each deployment mode its own bucket, queue, SSM parameters, secrets, and deploy role, but left ECR shared: the repositories `smart-tutor/<service>` belonged to native-cloud's `SmartTutor-prod-Registry` stack, on-premise pushed its images there, and the on-premise Host pulled them from there. Native-cloud's Registry could then never be torn down without breaking on-premise, and native-cloud's teardown had to keep it. The product owner and the cloud architect decided that the two modes must not share stacks (#206).

## Decision

- **Each mode has its own ECR repositories,** named after its data prefix: on-premise `smart-tutor-on-premise/<service>` in `SmartTutor-OnPremise-prod-Registry`; native-cloud keeps `smart-tutor/<service>` in `SmartTutor-prod-Registry`, the names the pilot was deployed with, so its Helm values don't change. Both use scan on push, keep the last 30 images, and delete their images on teardown.
- **Each mode's deploy role pushes only to its own repositories,** and the on-premise Host pulls only from on-premise's.
- **Every merge builds the images of each mode it deploys,** with that mode's role. A push that deploys both modes builds twice. Before its first push the build deploys its mode's `GitHubDeploy` and `Registry` stacks, so the repositories and the push permission exist; later builds find nothing to change.
- **A deploy or rollback looks only in its own mode's repositories.** It never falls back to the other mode's.
- **Shared, by exception:** the account's CDK bootstrap (`CDKToolkit`), and the GitHub OIDC provider. AWS allows one OIDC provider per URL in an account, so native-cloud's `GitHubDeploy` creates it and on-premise's `GitHubDeploy` imports it. Nothing else is shared.

## Alternatives rejected

- **Keep ECR shared.** Simple, but it ties on-premise's deploys to a native-cloud stack the product owner may want to tear down.
- **Rename native-cloud's repositories too** (for example `smart-tutor-native-cloud/*`). Symmetric, but it changes the pilot's Helm values and strands its existing images for no gain.
- **Copy images between the modes' repositories** instead of building per mode. One build, but one role would need to read the other mode's repositories, which is the coupling this decision removes.
- **A documented one-time `cdk deploy` before the first merge.** It works once, but a fresh account or a torn-down registry would need it again; the build deploying its own registry heals both.

## Consequences

- Native-cloud's teardown deletes its Registry too; a redeploy recreates it on the first build.
- A push with `NATIVE_CLOUD_AUTO_DEPLOY=true` builds the images twice.
- Commits merged before #206 have images only in `smart-tutor/*`. On-premise can't roll back to them unless their images are built into its repositories by hand (`docs/runbooks/on-premise-deploy.md`).
- The image build needs Node and uv and permission to deploy two stacks, which the deploy roles already had (through the CDK bootstrap roles).
```

- [ ] **Step 2: Update ADR 0012 and the ADR index**

ADR 0012: status line → `- Status: accepted; "ECR is shared" superseded by 0015 (the modes share no stack)`. In the Decision's first bullet, "ECR is shared." → "ECR was shared until ADR 0015 gave each mode its own repositories." Leave the rest (history).

`sdd/adr/README.md`: add row `| [0015](0015-deployment-modes-share-no-stack.md) | Deployment modes share no stack: each has its own ECR repositories; only the CDK bootstrap and the GitHub OIDC provider (native-cloud's GitHubDeploy owns it) are shared (supersedes 0012's "ECR is shared") |`.

- [ ] **Step 3: Update the PRD**

- Status line: `Draft v2.35` → `Draft v2.36` (keep the parenthetical).
- Insert above the `Changes from v2.34` row a new row: `| **Changes from v2.35** | Each deployment mode has its own image registry (#206; ADR 0015): on-premise pushes to and pulls from `smart-tutor-on-premise/<service>`, native-cloud keeps `smart-tutor/<service>`, and each mode's deploy role pushes only to its own. The modes share no stack except the account's CDK bootstrap and the GitHub OIDC provider. Appendix A. No product behavior changes. |` (match the exact table syntax of the neighboring rows).
- Line ~516: `ECR (shared by both modes)` → `ECR (each mode its own repositories)`.
- Line ~525: `; ECR is shared.` → `, and ECR repositories (on-premise `smart-tutor-on-premise/<service>`, native-cloud `smart-tutor/<service>`). The modes share no stack except the account's CDK bootstrap and the GitHub OIDC provider (ADR 0015).`
- Line ~535 (on-premise delivery): `images to ECR` → `images to on-premise's ECR repositories`.
- Line ~792 (instance role): `ECR pull` → `ECR pull from on-premise's repositories only`.
- Grep the PRD for any other `ECR` sentence that implies sharing and fix it.

- [ ] **Step 4: CONTEXT.md, structure spec, AGENTS.md**

CONTEXT.md, under **Deployment mode** definition, append: "Each mode has its own copy of every cloud resource it uses, image registry included; they share only the account's one-time setup." In **On-premise mode**, "and the image registry stay on" → "and its own image registry stay on".

Structure spec line 178: `budgets, github_deploy, host; ECR shared)` → `budgets, github_deploy, registry, host)`. Check lines 172-178 read correctly together.

AGENTS.md: `sdd/prd.md` (v2.35) → (v2.36); `sdd/adr/` (0001–0014) → (0001–0015).

- [ ] **Step 5: Verify and commit**

Run: `grep -rn "ECR is shared\|shared by both modes\|ECR shared" sdd CONTEXT.md AGENTS.md docs README.md` — expected: only ADR 0012's historical sentence and ADR 0015.
Run: `cd infra && uv run pytest -q` — PASS.

```bash
git add sdd CONTEXT.md AGENTS.md
git commit -m "Record that the deployment modes share no stack (ADR 0015, PRD v2.36) (#206)"
```
