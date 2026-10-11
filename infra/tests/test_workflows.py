"""Static checks of the GitHub Actions workflows (#59, #150): what runs, when, and with which AWS access."""

import re
from pathlib import Path
from typing import Any

import yaml

from smart_tutor_infra.app_stacks import ON_PREMISE_GITHUB_ENVIRONMENT
from smart_tutor_infra.names import MODES, NATIVE_CLOUD, ON_PREMISE, mode_names
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
    assert callers == 6  # deploy: images per mode, on-premise, native-cloud; rollback: on-premise, native-cloud
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


def test_rollback_redeploys_the_chosen_mode_without_infrastructure() -> None:
    jobs = workflow("rollback.yml")["jobs"]
    assert jobs["on-premise"]["if"] == "inputs.mode == 'on-premise'"
    assert jobs["on-premise"]["uses"] == "./.github/workflows/deploy-on-premise.yml"
    assert jobs["native-cloud"]["if"] == "inputs.mode == 'native-cloud'"
    assert jobs["native-cloud"]["uses"] == "./.github/workflows/deploy-native-cloud.yml"
    for job in jobs.values():
        assert job["with"] == {"image_tag": "${{ inputs.image_tag }}", "infrastructure": False}


# --- build-images.yml ------------------------------------------------------------------------------------------


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
    pattern = r"^\s*([\w-]+)\) stack_prefix=(\S+) repository_prefix=(\S+) ;;$"
    arms = {m: (s, r) for m, s, r in re.findall(pattern, run, re.MULTILINE)}
    assert arms == {m: (mode_names(m).stack_prefix, mode_names(m).repository_prefix) for m in MODES}
    # an unknown mode fails instead of falling back to one mode's repositories
    assert re.search(r"^\s*\*\) .*::error::.*exit 1", run, re.MULTILINE)
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
    # every deploy, including a rollback, checks
    assert "if" not in job["steps"][images]


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


def test_runbooks_name_the_current_workflows_and_environments() -> None:
    root = WORKFLOWS.parents[1]
    docs = [*(root / "docs").rglob("*.md"), *RUNBOOKS.glob("*.ps1"), root / "README.md"]
    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "deploy-pilot.yml" not in text, path.name
        assert "environment `pilot`" not in text and "`pilot` environment" not in text, path.name
    on_premise = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    for needle in ("deploy-on-premise.yml", "build-images.yml", "rollback.yml", "gh api -X PUT", "on-premise"):
        assert needle in on_premise, needle


def test_runbooks_no_longer_call_ecr_shared_and_explain_old_rollbacks() -> None:
    names = (
        "on-premise-deploy.md",
        "pilot-deploy.md",
        "pilot-environment-overview.md",
        "pilot-aws-prerequisites.md",
        "pilot-teardown.md",
        "pilot-teardown.ps1",
    )
    for name in names:
        text = (RUNBOOKS / name).read_text(encoding="utf-8")
        assert not re.search(r"shared with (native-cloud|on-premise)|[Ss]hared ECR|ECR is shared", text), name
    on_premise = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    assert "smart-tutor-on-premise/<service>" in on_premise
    assert "before #206" in on_premise  # what a rollback to an older commit does
    assert '"$Registry/smart-tutor/' not in on_premise  # the hand build pushes to on-premise's repositories
    assert "runs outside the `deploy-on-premise` queue" in on_premise  # the build can overlap a deploy
    assert "before #206" in (RUNBOOKS / "pilot-deploy.md").read_text(encoding="utf-8")
    for runbook in RUNBOOKS.glob("on-premise-*.md"):
        text = runbook.read_text(encoding="utf-8")
        assert not re.search(r"/smart-tutor/(api|web|keycloak|agent|mcp|worker)[:\"]", text), runbook.name
    teardown = (RUNBOOKS / "pilot-teardown.ps1").read_text(encoding="utf-8")
    assert '"Registry"' in teardown.split("$DeleteStacks")[1].split("$KeepStacks")[0]
