"""Static checks of the GitHub Actions workflows (#59): what runs, when, and with which AWS access."""

import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github/workflows"
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
    return "\n".join(
        str(s.get("run", "")) + str(s.get("uses", "")) + str(s.get("with", ""))
        for s in job["steps"]
    )


def test_ci_is_reusable_and_runs_infra_tests() -> None:
    ci = workflow("ci.yml")

    # a push to main runs it through deploy.yml
    assert set(ci["on"]) == {"pull_request", "workflow_call"}
    infra = ci["jobs"]["infra"]
    text = steps_text(infra)
    # chart tests skip without helm
    assert "azure/setup-helm" in text
    assert "uv run pytest" in text
    # the production lint, as the runbook deploys it
    assert "values-prod.yaml" in steps_text(ci["jobs"]["helm"])
    assert {"backend", "web", "design", "helm", "infra"} <= set(ci["jobs"])


def deploy_job() -> dict[str, Any]:
    return workflow("deploy-pilot.yml")["jobs"]["deploy"]


def test_only_main_and_rollback_reach_the_pilot_environment() -> None:
    assert set(workflow("deploy-pilot.yml")["on"]) == {"workflow_call"}
    assert workflow("deploy.yml")["on"] == {"push": {"branches": ["main"]}}
    assert set(workflow("rollback.yml")["on"]) == {"workflow_dispatch"}
    assert deploy_job()["environment"] == "pilot"
    for name in ("deploy.yml", "rollback.yml"):
        wf = workflow(name)
        assert wf["permissions"] == {"contents": "read", "id-token": "write"}, name
        assert any(
            j.get("uses") == "./.github/workflows/deploy-pilot.yml"
            for j in wf["jobs"].values()
        ), name
    # Only the pilot deploy job names the pilot deploy role (openwiki-update.yml has its own Bedrock-only role).
    for path in WORKFLOWS.glob("*.yml"):
        if path.name != "deploy-pilot.yml":
            assert "vars.AWS_ROLE_ARN" not in path.read_text(encoding="utf-8"), (
                path.name
            )
    assert "id-token" not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_no_long_lived_aws_keys() -> None:
    for name in ("ci.yml", "deploy.yml", "rollback.yml", "deploy-pilot.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert (
            "AWS_ACCESS_KEY_ID" not in text and "AWS_SECRET_ACCESS_KEY" not in text
        ), name
        assert "${{ secrets." not in text, name
    creds = next(
        s
        for s in deploy_job()["steps"]
        if "configure-aws-credentials" in str(s.get("uses"))
    )
    assert creds["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
    assert creds["with"]["aws-region"] == "${{ vars.AWS_REGION }}"


def test_deployments_never_overlap_or_cancel() -> None:
    assert deploy_job()["concurrency"] == {
        "group": "deploy-pilot",
        "cancel-in-progress": False,
    }


def test_deploy_needs_the_checks() -> None:
    jobs = workflow("deploy.yml")["jobs"]
    assert jobs["checks"]["uses"] == "./.github/workflows/ci.yml"
    assert jobs["deploy"]["needs"] == "checks"
    assert jobs["deploy"]["with"] == {"image_tag": "${{ github.sha }}", "build": True}


def test_merge_builds_pushes_and_deploys_in_order() -> None:
    text = steps_text(deploy_job())
    order = [
        "aws-cdk@2.1145.0 deploy --all --require-approval never",
        "docker push",
        "aws eks update-kubeconfig --name smart-tutor-prod",
        "helm upgrade --install aws-load-balancer-controller",
        "helm upgrade --install smart-tutor deploy/helm/smart-tutor",
        "deploy/pilot/smoke_test.py",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)
    for image in ("smart-tutor/api", "smart-tutor/web", "smart-tutor/keycloak"):
        assert image in text
    assert "--target api" in text
    assert "VITE_API_URL=/api" in text and "VITE_KEYCLOAK_URL=/auth" in text


def test_release_uses_the_tag_and_the_stack_outputs() -> None:
    text = steps_text(deploy_job())
    assert "global.imageTag=${{ inputs.image_tag }}" in text
    for output in ("RegistryUri", "CloudFrontUrl", "VpcId"):
        assert output in text
    assert "values-prod.yaml" in text and "--wait --timeout 15m" in text


def test_add_ons_match_the_runbook_versions() -> None:
    text = steps_text(deploy_job())
    runbook = (WORKFLOWS.parents[1] / "docs/runbooks/pilot-deploy.md").read_text(
        encoding="utf-8"
    )
    for chart, version in ADDON_VERSIONS.items():
        assert re.search(
            rf"upgrade --install {chart} \S+ --version {re.escape(version)}", text
        ), chart
        assert re.search(
            rf"upgrade --install {chart} \S+ --version {re.escape(version)}", runbook
        ), chart


def test_build_steps_only_run_when_building() -> None:
    for step in deploy_job()["steps"]:
        text = str(step.get("run", ""))
        if "aws-cdk@" in text or "docker build" in text or "docker push" in text:
            assert step.get("if") == "inputs.build", step.get("name")


def test_rollback_checks_the_images_exist_and_skips_build_and_cdk() -> None:
    rollback = workflow("rollback.yml")
    tag = rollback["on"]["workflow_dispatch"]["inputs"]["image_tag"]
    assert tag["required"] is True
    (job,) = rollback["jobs"].values()
    assert job["with"] == {"image_tag": "${{ inputs.image_tag }}", "build": False}
    steps = deploy_job()["steps"]
    checkout = next(s for s in steps if "actions/checkout" in str(s.get("uses")))
    assert (
        checkout["with"]["ref"] == "${{ inputs.image_tag }}"
    )  # the chart that matches the images
    verify = next(s for s in steps if "describe-images" in str(s.get("run", "")))
    assert verify["if"] == "${{ !inputs.build }}"
    assert "^[0-9a-f]{40}$" in str(verify["run"])


def test_smoke_test_runs_last_against_the_cloudfront_url() -> None:
    last = deploy_job()["steps"][-1]
    assert "deploy/pilot/smoke_test.py" in str(last["run"]) and "CLOUDFRONT_URL" in str(
        last["run"]
    )


def test_deploy_job_has_a_time_limit() -> None:
    assert deploy_job()["timeout-minutes"] == 60
