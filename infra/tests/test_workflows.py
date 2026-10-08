"""Static checks of the GitHub Actions workflows (#59): what runs, when, and with which AWS access."""

from pathlib import Path
from typing import Any

import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github/workflows"


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
