"""Renders the umbrella chart with `helm template` for chart tests; skips the test when helm is not installed."""

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

CHART = Path(__file__).parents[2] / "deploy/helm/smart-tutor"
PROD = ["-f", str(CHART / "values-prod.yaml")]
DEPLOY = ["--set", "global.publicUrl=https://d111.cloudfront.net", "--set", "global.imageRegistry=reg.example",
          "--set", "global.imageTag=abc123", "--set", "global.documentsBucket=docs-bucket",
          "--set", "global.ingestQueueUrl=https://sqs.us-east-1.amazonaws.com/123/smart-tutor-ingest"]


def render(*args: str) -> list[dict[str, Any]]:
    if shutil.which("helm") is None:
        pytest.skip("helm is not installed")
    out = subprocess.run(
        ["helm", "template", "smart-tutor", str(CHART), "--namespace", "smart-tutor", *args],
        check=True, capture_output=True, text=True,
    ).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def find(docs: list[dict[str, Any]], kind: str, name: str) -> dict[str, Any]:
    return next(d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name)
