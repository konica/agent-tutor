# Merging to main deploys the pilot environment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A push to `main` runs the checks, deploys the infrastructure with CDK, builds and pushes the api, web, and Keycloak images tagged with the commit SHA, upgrades the Helm release, and smoke-tests the public address; a failed step fails the run. A manual rollback workflow redeploys an earlier commit's images.

**Architecture:** Three workflows. `ci.yml` keeps running on pull requests and becomes reusable (`workflow_call`); it gains an `infra` job (CDK and chart tests with Helm installed, plus the production `helm lint`). `deploy.yml` runs on push to `main`: job `checks` calls `ci.yml`, job `deploy` calls the reusable `deploy-pilot.yml` with the commit SHA. `rollback.yml` runs on `workflow_dispatch` with an earlier SHA and calls `deploy-pilot.yml` with `build: false`. `deploy-pilot.yml` has one job in the GitHub environment `pilot` (concurrency group `deploy-pilot`, never cancelled): OIDC sign-in with the #55 deploy role → (build mode) `cdk deploy --all`, then build and push the three images → read the stack outputs → kubeconfig → add-ons (`helm upgrade --install`, pinned versions) → `helm upgrade --install smart-tutor` → `deploy/pilot/smoke_test.py`. A rollback checks out the old commit, so the chart matches the images, and skips CDK and the image build after checking that the images still exist in ECR.

**Tech Stack:** GitHub Actions (`actions/checkout@v4`, `aws-actions/configure-aws-credentials@v4`, `azure/setup-helm@v4`, `astral-sh/setup-uv@v6`, `actions/setup-node@v4`), AWS CDK CLI 2.1145.0, Helm v4.2.1, Docker, Python 3.12 stdlib (`urllib`, `http.server`) for the smoke test, pytest + PyYAML for tests.

**Spec:** GitHub issue #59 (parent #54); PRD §9.12 ("on merge to `main`: tests … → images to ECR → `cdk deploy` → `helm upgrade`"); `docs/runbooks/pilot-environment-overview.md` §4 "Deploy on merge"; `docs/runbooks/pilot-aws-prerequisites.md` steps 3–4 (deploy role, `pilot` environment); runbook `docs/runbooks/pilot-deploy.md` (the manual steps this automates).

**Facts checked on 2026-10-08:** the GitHub environment `pilot` exists, limited to `main` (custom branch policy), with variables `AWS_ROLE_ARN` (`arn:aws:iam::<ACCOUNT_ID>:role/smart-tutor-github-deploy`), `AWS_REGION` (`us-east-1`), `AWS_ACCOUNT_ID`. The deploy role trusts only `repo:konica@1114311/agent-tutor@1399048529:environment:pilot` and may assume the CDK bootstrap roles, push to `smart-tutor/*` ECR repositories (including `ecr:DescribeImages`), `eks:DescribeCluster`, and `cloudformation:DescribeStacks` on `SmartTutor-prod-*`; the Cluster stack gives it a cluster-admin access entry. So **no IAM change is needed**. ECR keeps the last 30 images per repository. The live address currently answers 504 everywhere: no add-ons and no release are installed, so the first run is a first install (add-ons included).

## Global Constraints

- Workflows: `.github/workflows/ci.yml` (PRs + `workflow_call`; **no** `push` trigger any more, so a merge doesn't run the checks twice), `.github/workflows/deploy.yml` (push to `main` only), `.github/workflows/rollback.yml` (`workflow_dispatch` only), `.github/workflows/deploy-pilot.yml` (`workflow_call` only).
- The deploy job: `environment: pilot`; `concurrency: {group: deploy-pilot, cancel-in-progress: false}`; `timeout-minutes: 60`; credentials only through `aws-actions/configure-aws-credentials@v4` with `role-to-assume: ${{ vars.AWS_ROLE_ARN }}` and `aws-region: ${{ vars.AWS_REGION }}`; no `secrets.*` and no AWS access-key variables anywhere. Callers grant `permissions: {contents: read, id-token: write}`.
- Image tag: the full 40-character commit SHA (`github.sha`). Rollback input `image_tag` must match `^[0-9a-f]{40}$`; the job checks it exists in all three ECR repositories before touching the cluster.
- Images: `smart-tutor/api` (`docker build --target api backend`), `smart-tutor/web` (`docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth web`), `smart-tutor/keycloak` (`docker build deploy/keycloak`); `linux/amd64` (GitHub's ubuntu runners are amd64).
- Stack outputs read with `aws cloudformation describe-stacks`: `SmartTutor-prod-Registry` `RegistryUri`, `SmartTutor-prod-Edge` `CloudFrontUrl`, `SmartTutor-prod-Network` `VpcId`. Cluster name `smart-tutor-prod`.
- Tools pinned: CDK CLI `aws-cdk@2.1145.0` (via `npx`), Helm `v4.2.1`, Node 22. Add-on charts exactly as runbook step 4: `eks/aws-load-balancer-controller` `3.5.0` (`-n kube-system`, `--set vpcId=…`), `external-secrets/external-secrets` `2.11.0` (`-n external-secrets --create-namespace`), `metrics-server/metrics-server` `3.14.0` (`-n kube-system`), each with `-f deploy/helm/addons/<name>.yaml --wait`.
- App release: `helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace -f deploy/helm/smart-tutor/values-prod.yaml --set global.imageRegistry=<RegistryUri> --set global.imageTag=<tag> --set global.publicUrl=<CloudFrontUrl> --wait --timeout 15m`. No automatic rollback: a failed release fails the run and stays visible (`helm history`).
- `cdk deploy --all --require-approval never` from `infra/` after `uv sync --frozen`; it includes `SmartTutor-prod-GitHubDeploy`, which the workflow may update (`github_deploy.py` docstring).
- Smoke test (`deploy/pilot/smoke_test.py <url>`), all against the public address, retried every 15 s until all pass or 10 minutes pass: `GET /` → 200 with `<div id="root">` in the body; `GET /api/healthz` → 200; `GET /api/me` without a token → 401 with a `WWW-Authenticate` header starting `Bearer`; `GET /auth/realms/smart-tutor/.well-known/openid-configuration` → 200 JSON whose `issuer` is exactly `<url>/auth/realms/smart-tutor`. Exit 0 on success; exit 1 with one line per failing check otherwise. Stdlib only. It never sends a token.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q`; `cd infra && uv run ruff check . && uv run ruff format --check <changed files>`; `helm lint deploy/helm/smart-tutor`. No task runs a workflow, pushes, or calls AWS.

## Review Focus

1. **A pull request or another branch getting AWS credentials.** Only `deploy-pilot.yml` names the pilot deploy role, only inside `environment: pilot`, and only `deploy.yml` (push to `main`) and `rollback.yml` (dispatch, which the environment's branch policy limits to `main`) call it. Pinned in Task 3 (`test_only_main_and_rollback_reach_the_pilot_environment`, `test_no_long_lived_aws_keys`).
2. **Two deployments at once** (a merge during a rollback, two quick merges). Pinned in Task 3 (`test_deployments_never_overlap_or_cancel`).
3. **A deploy that "passes" while the site is broken** (502 from new targets, wrong issuer, API down). Pinned in Task 1 (`test_wrong_issuer_fails`, `test_retries_until_the_site_settles`, `test_gives_up_with_the_failing_checks`) and Task 3 (`test_smoke_test_runs_last_against_the_cloudfront_url`).
4. **Rolling back to a tag ECR no longer has, or across a migration.** Pinned in Task 3 (`test_rollback_checks_the_images_exist_and_skips_build_and_cdk`); the migration caveat (the `migrate` hook fails, so the release stops) is documented in Task 4.
5. **The checks being skipped before a deploy.** Pinned in Task 3 (`test_deploy_needs_the_checks`) and Task 2 (`test_ci_is_reusable_and_runs_infra_tests`).

---

### Task 1: The smoke test

**Files:**
- Create: `deploy/pilot/smoke_test.py`
- Test: `infra/tests/test_smoke_test.py`

**Interfaces:**
- Produces: CLI `python3 deploy/pilot/smoke_test.py <url> [--deadline-seconds N] [--interval-seconds N]` (defaults 600 and 15); exit 0 when every check passes, 1 otherwise. Module function `run_checks(url: str) -> list[str]` returns the failure messages (empty when all pass). Task 3 calls the CLI.

- [ ] **Step 1: Write the failing tests**

```python
"""The post-deploy smoke test (deploy/pilot/smoke_test.py) against a local fake of the public address."""

import importlib.util
import json
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "deploy/pilot/smoke_test.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smoke_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


smoke = load()

Route = tuple[int, dict[str, str], bytes]


def healthy(base: str) -> dict[str, Route]:
    issuer = f"{base}/auth/realms/smart-tutor"
    return {
        "/": (200, {"Content-Type": "text/html"}, b'<html><body><div id="root"></div></body></html>'),
        "/api/healthz": (200, {"Content-Type": "application/json"}, b'{"status":"ok"}'),
        "/api/me": (401, {"WWW-Authenticate": "Bearer", "Content-Type": "application/json"}, b'{"detail":"x"}'),
        "/auth/realms/smart-tutor/.well-known/openid-configuration": (
            200,
            {"Content-Type": "application/json"},
            json.dumps({"issuer": issuer}).encode(),
        ),
    }


@pytest.fixture
def site() -> Iterator[tuple[str, Callable[[dict[str, Route]], None], list[str]]]:
    """A local server whose routes the test sets; it records whether any request carried Authorization."""
    routes: dict[str, Route] = {}
    auth_seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Authorization"):
                auth_seen.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b""))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"

    def set_routes(new: dict[str, Route]) -> None:
        routes.clear()
        routes.update(new)

    yield base, set_routes, auth_seen
    server.shutdown()


def test_healthy_site_passes(site) -> None:
    base, set_routes, auth_seen = site
    set_routes(healthy(base))
    assert smoke.run_checks(base) == []
    assert auth_seen == []  # the smoke test never sends a token


def test_trailing_slash_in_url_is_ignored(site) -> None:
    base, set_routes, _ = site
    set_routes(healthy(base))
    assert smoke.run_checks(base + "/") == []


def test_wrong_issuer_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/auth/realms/smart-tutor/.well-known/openid-configuration"] = (
        200,
        {"Content-Type": "application/json"},
        json.dumps({"issuer": "http://internal-alb/auth/realms/smart-tutor"}).encode(),
    )
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "issuer" in failures[0]


def test_api_me_must_challenge_with_bearer(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (401, {}, b"")  # no WWW-Authenticate
    set_routes(routes)
    failures = smoke.run_checks(base)
    assert len(failures) == 1 and "/api/me" in failures[0]


def test_api_me_answering_200_without_token_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/api/me"] = (200, {"Content-Type": "application/json"}, b"{}")
    set_routes(routes)
    assert any("/api/me" in f for f in smoke.run_checks(base))


def test_web_without_app_shell_fails(site) -> None:
    base, set_routes, _ = site
    routes = healthy(base)
    routes["/"] = (200, {"Content-Type": "text/html"}, b"<html>maintenance</html>")
    set_routes(routes)
    assert any(f.startswith("/ ") or "app shell" in f for f in smoke.run_checks(base))


def test_unreachable_site_reports_every_check() -> None:
    failures = smoke.run_checks("http://127.0.0.1:9")  # nothing listens on the discard port
    assert len(failures) == 4


def test_retries_until_the_site_settles(site) -> None:
    base, set_routes, _ = site
    set_routes({p: (502, {}, b"") for p in healthy(base)})
    timer = threading.Timer(0.5, lambda: set_routes(healthy(base)))
    timer.start()
    assert smoke.main([base, "--deadline-seconds", "10", "--interval-seconds", "0.2"]) == 0


def test_gives_up_with_the_failing_checks(site, capsys) -> None:
    base, set_routes, _ = site
    set_routes({p: (503, {}, b"") for p in healthy(base)})
    assert smoke.main([base, "--deadline-seconds", "0.5", "--interval-seconds", "0.1"]) == 1
    out = capsys.readouterr().out
    assert "/api/me" in out and "openid-configuration" in out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_smoke_test.py -q`
Expected: collection error — `deploy/pilot/smoke_test.py` does not exist.

- [ ] **Step 3: Implement `deploy/pilot/smoke_test.py`**

```python
#!/usr/bin/env python3
"""Smoke-test the pilot's public address after a deploy (#59): the web app shell, the API, and Keycloak's issuer.

Usage: python3 deploy/pilot/smoke_test.py https://<id>.cloudfront.net [--deadline-seconds 600] [--interval-seconds 15]

Retries until every check passes or the deadline passes, because new targets and a new distribution answer 502/503 for
a few minutes. Exit 0 when all checks pass, 1 otherwise. Standard library only; never sends a token.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass

REQUEST_TIMEOUT = 10
REALM_PATH = "/auth/realms/smart-tutor"


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]
    body: bytes


def fetch(url: str) -> Response:
    request = urllib.request.Request(url, headers={"User-Agent": "smart-tutor-smoke-test"})
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as r:  # noqa: S310 (our own https address)
            return Response(r.status, {k.lower(): v for k, v in r.headers.items()}, r.read())
    except urllib.error.HTTPError as e:
        return Response(e.code, {k.lower(): v for k, v in e.headers.items()}, e.read())


def check_web(base: str) -> str | None:
    r = fetch(f"{base}/")
    if r.status != 200 or b'<div id="root">' not in r.body:
        return f"/ gave {r.status}, expected 200 with the app shell"
    return None


def check_health(base: str) -> str | None:
    r = fetch(f"{base}/api/healthz")
    return None if r.status == 200 else f"/api/healthz gave {r.status}, expected 200"


def check_api_rejects_anonymous(base: str) -> str | None:
    r = fetch(f"{base}/api/me")
    challenge = r.headers.get("www-authenticate", "")
    if r.status != 401 or not challenge.startswith("Bearer"):
        return f"/api/me without a token gave {r.status} (WWW-Authenticate {challenge!r}), expected 401 Bearer"
    return None


def check_issuer(base: str) -> str | None:
    expected = f"{base}{REALM_PATH}"
    r = fetch(f"{base}{REALM_PATH}/.well-known/openid-configuration")
    if r.status != 200:
        return f"openid-configuration gave {r.status}, expected 200"
    try:
        issuer = json.loads(r.body).get("issuer")
    except ValueError:
        return "openid-configuration is not JSON"
    return None if issuer == expected else f"issuer is {issuer!r}, expected {expected!r}"


CHECKS = (check_web, check_health, check_api_rejects_anonymous, check_issuer)


def run_checks(url: str) -> list[str]:
    base = url.rstrip("/")
    failures = []
    for check in CHECKS:
        try:
            failure = check(base)
        except (urllib.error.URLError, OSError) as e:
            failure = f"{check.__name__}: {e}"
        if failure:
            failures.append(failure)
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url")
    parser.add_argument("--deadline-seconds", type=float, default=600)
    parser.add_argument("--interval-seconds", type=float, default=15)
    args = parser.parse_args(argv)

    deadline = time.monotonic() + args.deadline_seconds
    attempt = 0
    while True:
        attempt += 1
        failures = run_checks(args.url)
        if not failures:
            print(f"smoke test passed on attempt {attempt}: {args.url}")
            return 0
        if time.monotonic() + args.interval_seconds > deadline:
            print(f"smoke test FAILED after {attempt} attempts against {args.url}:")
            for failure in failures:
                print(f"  - {failure}")
            return 1
        print(f"attempt {attempt}: {len(failures)} check(s) failing, retrying in {args.interval_seconds:g}s")
        time.sleep(args.interval_seconds)


if __name__ == "__main__":
    sys.exit(main())
```

Note: `check_issuer` compares against `base` with the scheme the caller gives; the workflow passes the `https://` CloudFront URL.

- [ ] **Step 4: Run the tests and ruff**

Run: `cd infra && uv run pytest tests/test_smoke_test.py -q && uv run ruff check ../deploy/pilot/smoke_test.py tests/test_smoke_test.py`
Expected: PASS (9 tests), ruff clean.

- [ ] **Step 5: Commit**

```bash
git add deploy/pilot/smoke_test.py infra/tests/test_smoke_test.py
git commit -m "Add a smoke test for the pilot's public address" -m "Deploy on merge (#59) must fail visibly when the site is broken after a release: the web shell, /api/healthz, the API's 401 Bearer challenge, and Keycloak's public issuer, retried while new targets settle."
```

---

### Task 2: CI is reusable and runs the infra tests

**Files:**
- Modify: `.github/workflows/ci.yml`
- Test: `infra/tests/test_workflows.py` (create; Task 3 appends to it)

**Interfaces:**
- Produces: `ci.yml` callable with `uses: ./.github/workflows/ci.yml` (no inputs, no secrets). Test helper `workflow(name: str) -> dict` in `test_workflows.py`, which Task 3 reuses.

- [ ] **Step 1: Write the failing test** (`infra/tests/test_workflows.py`)

```python
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
    return "\n".join(str(s.get("run", "")) + str(s.get("uses", "")) + str(s.get("with", "")) for s in job["steps"])


def test_ci_is_reusable_and_runs_infra_tests() -> None:
    ci = workflow("ci.yml")

    assert set(ci["on"]) == {"pull_request", "workflow_call"}  # a push to main runs it through deploy.yml
    infra = ci["jobs"]["infra"]
    text = steps_text(infra)
    assert "azure/setup-helm" in text  # chart tests skip without helm
    assert "uv run pytest" in text
    assert "values-prod.yaml" in text  # the production lint, as the runbook deploys it
    assert {"backend", "web", "design", "helm", "infra"} <= set(ci["jobs"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: FAIL — `on` has `push`, no `workflow_call`, no `infra` job.

- [ ] **Step 3: Change `ci.yml`**

Replace the trigger:

```yaml
on:
  pull_request:
  # deploy.yml calls this on every push to main, before it deploys.
  workflow_call:
```

Add after the `helm` job's `helm lint deploy/helm/smart-tutor` step, in the same job:

```yaml
      - name: Production values lint
        run: helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml --set global.publicUrl=https://d111.cloudfront.net
```

Pin that job's helm: `- uses: azure/setup-helm@v4` gets `with: {version: v4.2.1}`.

Add a new job:

```yaml
  infra:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra
    env:
      JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - uses: azure/setup-helm@v4
        with:
          version: v4.2.1
      - uses: astral-sh/setup-uv@v6
      - run: uv sync --frozen
      - name: CDK, chart, workflow, and smoke-test tests
        run: uv run pytest -q
```

- [ ] **Step 4: Run the infra tests**

Run: `cd infra && JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION=1 uv run pytest -q`
Expected: PASS (all existing tests plus the new one).

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml infra/tests/test_workflows.py
git commit -m "Run the infra tests in CI and let the deploy reuse CI" -m "The CDK, chart, and production-render tests never ran in CI, so nothing guarded the pilot's infrastructure. ci.yml becomes callable so the deploy on merge runs exactly the same checks first, and it no longer runs a second time on push."
```

---

### Task 3: Deploy on merge, roll back on demand

**Files:**
- Create: `.github/workflows/deploy-pilot.yml`, `.github/workflows/deploy.yml`, `.github/workflows/rollback.yml`
- Modify: `infra/tests/test_workflows.py` (append)

**Interfaces:**
- Consumes: `deploy/pilot/smoke_test.py` CLI (Task 1); `ci.yml` via `workflow_call` and `workflow()`, `steps_text()` helpers (Task 2).
- Produces: reusable `deploy-pilot.yml` with inputs `image_tag` (string, required) and `build` (boolean, required).

- [ ] **Step 1: Write the failing tests** (append to `infra/tests/test_workflows.py`)

```python
import re

ADDON_VERSIONS = {"aws-load-balancer-controller": "3.5.0", "external-secrets": "2.11.0", "metrics-server": "3.14.0"}


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
        assert any(j.get("uses") == "./.github/workflows/deploy-pilot.yml" for j in wf["jobs"].values()), name
    # Only the pilot deploy job names the pilot deploy role (openwiki-update.yml has its own Bedrock-only role).
    for path in WORKFLOWS.glob("*.yml"):
        if path.name != "deploy-pilot.yml":
            assert "vars.AWS_ROLE_ARN" not in path.read_text(encoding="utf-8"), path.name
    assert "id-token" not in (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")


def test_no_long_lived_aws_keys() -> None:
    for name in ("ci.yml", "deploy.yml", "rollback.yml", "deploy-pilot.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        assert "AWS_ACCESS_KEY_ID" not in text and "AWS_SECRET_ACCESS_KEY" not in text, name
        assert "secrets." not in text, name
    creds = next(s for s in deploy_job()["steps"] if "configure-aws-credentials" in str(s.get("uses")))
    assert creds["with"]["role-to-assume"] == "${{ vars.AWS_ROLE_ARN }}"
    assert creds["with"]["aws-region"] == "${{ vars.AWS_REGION }}"


def test_deployments_never_overlap_or_cancel() -> None:
    assert deploy_job()["concurrency"] == {"group": "deploy-pilot", "cancel-in-progress": False}


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
    runbook = (WORKFLOWS.parents[1] / "docs/runbooks/pilot-deploy.md").read_text(encoding="utf-8")
    for chart, version in ADDON_VERSIONS.items():
        assert re.search(rf"upgrade --install {chart} \S+ --version {re.escape(version)}", text), chart
        assert re.search(rf"upgrade --install {chart} \S+ --version {re.escape(version)}", runbook), chart


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
    assert checkout["with"]["ref"] == "${{ inputs.image_tag }}"  # the chart that matches the images
    verify = next(s for s in steps if "describe-images" in str(s.get("run", "")))
    assert verify["if"] == "${{ !inputs.build }}"
    assert "^[0-9a-f]{40}$" in str(verify["run"])


def test_smoke_test_runs_last_against_the_cloudfront_url() -> None:
    last = deploy_job()["steps"][-1]
    assert "deploy/pilot/smoke_test.py" in str(last["run"]) and "CLOUDFRONT_URL" in str(last["run"])


def test_deploy_job_has_a_time_limit() -> None:
    assert deploy_job()["timeout-minutes"] == 60
```

Note on `if`: in the YAML write `if: inputs.build` for build steps and `if: ${{ !inputs.build }}` for the image check (a leading `!` needs the `${{ }}` form); the tests assert those exact strings.

- [ ] **Step 2: Run them to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: the new tests FAIL (`deploy-pilot.yml` not found); Task 2's test passes.

- [ ] **Step 3: Write `.github/workflows/deploy-pilot.yml`**

```yaml
# Deploys the pilot (PRD §9.12, #59). Called by deploy.yml (every push to main, after the checks) and rollback.yml.
# Signs in to AWS with the GitHub OIDC deploy role (#55), which trusts only jobs in the `pilot` environment.
name: deploy-pilot

on:
  workflow_call:
    inputs:
      image_tag:
        description: Commit SHA whose images to deploy
        type: string
        required: true
      build:
        description: Deploy the infrastructure and build the images (false for a rollback)
        type: boolean
        required: true

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: pilot
    # One deployment at a time; a queued one waits instead of cancelling the running release.
    concurrency:
      group: deploy-pilot
      cancel-in-progress: false
    timeout-minutes: 60
    env:
      AWS_REGION: ${{ vars.AWS_REGION }}
      IMAGE_TAG: ${{ inputs.image_tag }}
      JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION: "1"
    steps:
      # A rollback checks out the old commit, so the chart matches its images.
      - uses: actions/checkout@v4
        with:
          ref: ${{ inputs.image_tag }}

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ vars.AWS_ROLE_ARN }}
          aws-region: ${{ vars.AWS_REGION }}

      - uses: actions/setup-node@v4
        if: inputs.build
        with:
          node-version: 22
      - uses: astral-sh/setup-uv@v6
        if: inputs.build

      - name: Deploy the infrastructure (CDK)
        if: inputs.build
        working-directory: infra
        run: |
          uv sync --frozen
          npx --yes aws-cdk@2.1145.0 deploy --all --require-approval never

      - name: Read the stack outputs
        run: |
          output() {
            aws cloudformation describe-stacks --stack-name "SmartTutor-prod-$1" \
              --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
          }
          echo "REGISTRY=$(output Registry RegistryUri)" >> "$GITHUB_ENV"
          echo "CLOUDFRONT_URL=$(output Edge CloudFrontUrl)" >> "$GITHUB_ENV"
          echo "VPC_ID=$(output Network VpcId)" >> "$GITHUB_ENV"

      - name: Check the images to roll back to exist
        if: ${{ !inputs.build }}
        run: |
          [[ "$IMAGE_TAG" =~ ^[0-9a-f]{40}$ ]] || { echo "image_tag must be a full 40-character commit SHA"; exit 1; }
          for repo in api web keycloak; do
            aws ecr describe-images --repository-name "smart-tutor/$repo" --image-ids imageTag="$IMAGE_TAG" > /dev/null \
              || { echo "smart-tutor/$repo:$IMAGE_TAG is not in ECR (it keeps the last 30 images)"; exit 1; }
          done

      - name: Build the images
        if: inputs.build
        run: |
          aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
          docker build --target api -t "$REGISTRY/smart-tutor/api:$IMAGE_TAG" backend
          docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$REGISTRY/smart-tutor/web:$IMAGE_TAG" web
          docker build -t "$REGISTRY/smart-tutor/keycloak:$IMAGE_TAG" deploy/keycloak

      - name: Push the images
        if: inputs.build
        run: |
          for repo in api web keycloak; do docker push "$REGISTRY/smart-tutor/$repo:$IMAGE_TAG"; done

      - uses: azure/setup-helm@v4
        with:
          version: v4.2.1

      - name: Connect to the cluster
        run: aws eks update-kubeconfig --name smart-tutor-prod --region "$AWS_REGION"

      - name: Install the cluster add-ons
        run: |
          helm repo add eks https://aws.github.io/eks-charts
          helm repo add external-secrets https://charts.external-secrets.io
          helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
          helm repo update
          helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f deploy/helm/addons/aws-load-balancer-controller.yaml --set vpcId="$VPC_ID" --wait
          helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets --create-namespace -f deploy/helm/addons/external-secrets.yaml --wait
          helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 -n kube-system -f deploy/helm/addons/metrics-server.yaml --wait

      - name: Release the app (Helm)
        run: |
          helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace \
            -f deploy/helm/smart-tutor/values-prod.yaml \
            --set global.imageRegistry="$REGISTRY" --set global.imageTag=${{ inputs.image_tag }} \
            --set global.publicUrl="$CLOUDFRONT_URL" --wait --timeout 15m
          echo "Deployed \`$IMAGE_TAG\` to $CLOUDFRONT_URL" >> "$GITHUB_STEP_SUMMARY"

      - name: Smoke test the public address
        run: python3 deploy/pilot/smoke_test.py "$CLOUDFRONT_URL"
```

- [ ] **Step 4: Write `.github/workflows/deploy.yml`**

```yaml
# Every push to main: the CI checks, then the pilot deploy (PRD §9.12, #59). Runbook: docs/runbooks/pilot-deploy.md.
name: deploy

on:
  push:
    branches: [main]

permissions:
  contents: read
  id-token: write  # OIDC sign-in to AWS, used only inside the `pilot` environment

jobs:
  checks:
    uses: ./.github/workflows/ci.yml

  deploy:
    needs: checks
    uses: ./.github/workflows/deploy-pilot.yml
    with:
      image_tag: ${{ github.sha }}
      build: true
```

- [ ] **Step 5: Write `.github/workflows/rollback.yml`**

```yaml
# Redeploys an earlier commit's images and chart, without CDK or a build (#59). Runbook: docs/runbooks/pilot-deploy.md.
# The `pilot` environment only accepts runs from main: start it from main with the SHA to go back to.
name: rollback

on:
  workflow_dispatch:
    inputs:
      image_tag:
        description: Full commit SHA of an earlier deploy (its images must still be in ECR)
        type: string
        required: true

permissions:
  contents: read
  id-token: write  # OIDC sign-in to AWS, used only inside the `pilot` environment

jobs:
  rollback:
    uses: ./.github/workflows/deploy-pilot.yml
    with:
      image_tag: ${{ inputs.image_tag }}
      build: false
```

- [ ] **Step 6: Run the tests and lint the YAML**

Run: `cd infra && uv run pytest tests/test_workflows.py -q`
Expected: PASS. If `actionlint` is available (`actionlint -version`), also run `actionlint .github/workflows/*.yml` from the repository root and fix what it reports; if not available, say so in the report.

Note for `ci.yml` jobs called from `deploy.yml`: a reusable workflow's jobs inherit the caller's `permissions`, so CI jobs get `id-token: write` without asking for it; that's harmless (they're not in the `pilot` environment, and the role trusts only that environment).

- [ ] **Step 7: Commit**

```bash
git add .github/workflows infra/tests/test_workflows.py
git commit -m "Deploy the pilot on every merge to main, with a rollback workflow" -m "PRD §9.12: checks, cdk deploy, images tagged with the commit SHA, helm upgrade, then a smoke test of the public address, one deployment at a time and only from the pilot environment. A rollback redeploys an earlier commit's images and chart without building."
```

---

### Task 4: The runbook covers deploy on merge and rollback

**Files:**
- Modify: `docs/runbooks/pilot-deploy.md`
- Modify: `docs/runbooks/pilot-environment-overview.md` (§4 "Deploy on merge" and the §5 #59 row)

- [ ] **Step 1: Edit `pilot-deploy.md`**

- Title `# Pilot deploy (#56, #57, #58, #59)`; first paragraph: add "After the first deploy, every merge to `main` deploys automatically (section 12); this runbook stays the manual path and the reference for what the workflow does."
- Step 9 "Update after a change": start with "Merging to `main` does all of this (section 12). By hand:" and keep the existing text.
- New section `## 12. Deploy on merge and roll back (#59)`:
  - What runs: `.github/workflows/deploy.yml` on every push to `main`: the CI checks (`ci.yml`), then `deploy-pilot.yml` in the `pilot` environment: `cdk deploy --all`, the three images tagged with the full commit SHA, the add-ons, `helm upgrade --install smart-tutor`, and `deploy/pilot/smoke_test.py` against the CloudFront address. One deployment runs at a time; a second merge waits.
  - Watch it: `gh run list --workflow deploy.yml --limit 5` and `gh run watch`. The run summary names the deployed SHA and address. A red step is the failure; the release stays as Helm left it (`helm -n smart-tutor history smart-tutor`).
  - Optional approval: **Settings → Environments → pilot → Required reviewers** makes each deploy wait for an approval.
  - Smoke test by hand: `python deploy/pilot/smoke_test.py $Url`.
  - Roll back: `gh workflow run rollback.yml --ref main -f image_tag=<full SHA of an earlier successful deploy>` (find it with `gh run list --workflow deploy.yml --status success`). It checks the images are still in ECR (the last 30 per repository), checks out that commit's chart, and runs the add-ons, `helm upgrade`, and the smoke test, without CDK or a build. It doesn't undo infrastructure changes.
  - Rollback across a migration doesn't work: the old image's `migrate` hook can't find the newer Alembic revision in the database, so the release stops before anything rolls out. Fix forward instead (revert the PR and merge).
  - By hand (laptop) instead: steps 3 and 6 with `$Tag` set to the earlier SHA.
- [ ] **Step 2: Edit `pilot-environment-overview.md`**

In §4, under the diagram, name the files: `deploy.yml` (trigger), `ci.yml` (checks), `deploy-pilot.yml` (the job in `pilot`), `rollback.yml`; the add-ons install also runs on each deploy; replace "(the #59 runbook)" with "(`pilot-deploy.md` section 12)". In the §5 table's #59 row, "How" becomes `.github/workflows/deploy.yml`, `deploy-pilot.yml`, `rollback.yml`; `deploy/pilot/smoke_test.py`.

- [ ] **Step 3: Check and commit**

Run: `cd infra && uv run pytest tests/test_workflows.py -q` (the add-on versions test reads the runbook).

```bash
git add docs/runbooks
git commit -m "Document deploy on merge and rollback in the pilot runbook" -m "Says what the workflow does, how to watch a run, how to roll back with rollback.yml, and why a rollback across a migration stops instead of rolling out."
```
