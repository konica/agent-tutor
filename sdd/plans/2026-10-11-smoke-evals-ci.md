# Smoke evals in CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull requests that change the agent run the smoke split in GitHub Actions and fail on a breached threshold; the job summary shows the gate table and the experiment link (issue #226).

**Architecture:** A new workflow `.github/workflows/evals-smoke.yml` (path-filtered `pull_request` + `workflow_dispatch`) checks it can use the eval secrets, builds the Compose app images, signs in to AWS through GitHub OIDC with a Bedrock-only role, starts the stack with a CI override (`compose.ci.yaml`) that passes the OIDC session and LangSmith key into the containers, loads the eval learners, and runs `evals.run --split smoke --summary "$GITHUB_STEP_SUMMARY"`. The gate gains a Markdown renderer for the summary. The role's trust and permissions policies are checked-in JSON with a runbook; infra tests keep them in step with the model IDs and the OIDC subject.

**Tech Stack:** GitHub Actions, Docker Compose, Python 3.12 (uv, pytest), LangSmith, AWS IAM (GitHub OIDC).

**Spec:** Issue #226 (PRD §10.3 item 6). Runner from #223: `backend/evals/run.py`, `backend/evals/gate.py`.

## Global Constraints

- Third-party actions pinned to a 40-character SHA with a version comment, set up before `configure-aws-credentials` (`infra/tests/test_workflows.py` convention). SHAs to use: `actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0`, `astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0`, `aws-actions/configure-aws-credentials@7474bc4690e29a8392af63c5b98e7449536d5c3a # v4.3.1`.
- No workflow file may contain the strings `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` (`test_no_long_lived_aws_keys`); credential pass-through lives in `compose.ci.yaml`.
- No `${{ ... }}` expressions inside `run:` scripts; pass values through `env:`.
- Role ARN: repository variable `EVALS_AWS_ROLE_ARN` (repo convention for role ARNs, e.g. `OPENWIKI_AWS_ROLE_ARN`); LangSmith key: repository secret `LANGSMITH_API_KEY`; LangSmith project `smart-tutor-ci`; region `us-east-1`.
- OIDC subject prefix comes from `infra/cdk.json` context `smart-tutor:github-oidc-subject-prefix` (`repo:konica@1114311/agent-tutor@1399048529`).
- Bedrock models (backend `shared/config.py`): agent profile `us.amazon.nova-2-lite-v1:0` (foundation model `amazon.nova-2-lite-v1:0` in us-east-1, us-east-2, us-west-2), embeddings `amazon.nova-2-multimodal-embeddings-v1:0`, judge `qwen.qwen3-32b-v1:0`.
- Job `timeout-minutes: 60`, within the role's 1-hour session.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; infra: `cd infra && uv run pytest`.

## Review Focus

- A fork PR (no secrets, no OIDC token): the job passes with a notice and a summary line saying why it skipped; it never tries to assume the role. (Task 3 workflow test.)
- A same-repo PR before the maintainer has created the role/secret: skip with a warning naming the missing variable/secret and the runbook. (Task 3 workflow test.)
- The runner stops before the gate (LangSmith down, learners not loaded): the summary still says why, not blank. (Task 1 test.)
- An experiment with no URL (runner falls back to the experiment name): the summary shows the name as text, not a broken link. (Task 1 test.)
- A model ID changes in `config.py` without the IAM policy: an infra test fails. (Task 2 test.)

---

### Task 1: Gate table as Markdown in the job summary

**Files:**
- Modify: `backend/evals/gate.py` (add `render_markdown`)
- Modify: `backend/evals/run.py` (add `--summary PATH`)
- Test: `backend/tests/unit/evals/test_gate.py`, `backend/tests/unit/evals/test_run.py`
- Modify: `backend/evals/README.md` ("Run a split": mention `--summary` and CI)

**Interfaces:**
- Produces: `render_markdown(rows: Sequence[Row], links: Mapping[str, str], title: str) -> str`; CLI flag `--summary PATH` that **appends** Markdown to PATH (GitHub's `$GITHUB_STEP_SUMMARY` is append-only by convention).

- [ ] **Step 1: Failing gate test** in `test_gate.py`:

```python
def test_the_markdown_table_links_each_experiment_and_says_the_verdict() -> None:
    rows = check([SEARCH, RELEVANCE, INJECTION], {"search_step_ran": [1.0], "answer_relevance": [0.5]})
    text = render_markdown(rows, {"smart-tutor-ask (smoke smoke-v1)": "https://smith.langchain.com/x"}, "Smoke evals")
    lines = text.splitlines()
    assert lines[0] == "### Smoke evals: FAIL (1 passed, 1 failed, 1 not run)"
    assert "| metric | target | observed | examples | result |" in lines
    assert "| search_step_ran | >= 1.00 | 1.000 | 1 | PASS |" in lines
    assert "| answer_relevance | >= 0.85 | 0.500 | 1 | **FAIL** |" in lines
    assert "| injection_resistance | <= 0 failures | - | 0 | not run |" in lines
    assert "- [smart-tutor-ask (smoke smoke-v1)](https://smith.langchain.com/x)" in lines


def test_an_experiment_without_a_url_is_named_not_linked() -> None:
    rows = check([SEARCH], {"search_step_ran": [1.0]})
    text = render_markdown(rows, {"smart-tutor-ask (smoke smoke-v1)": "smart-tutor-ask-smoke-1a2b"}, "Smoke evals")
    assert "- smart-tutor-ask (smoke smoke-v1): smart-tutor-ask-smoke-1a2b" in text.splitlines()
```

(Check `RELEVANCE`'s threshold value in the test module's fixtures and adjust `>= 0.85` if it differs.)

- [ ] **Step 2:** `cd backend && uv run pytest tests/unit/evals/test_gate.py -q` → FAIL (ImportError `render_markdown`).

- [ ] **Step 3: Implement** in `gate.py`, reusing `_target`/`_observed`, and factor the verdict line's counts so `render` and `render_markdown` share it:

```python
def _verdict(rows: Sequence[Row]) -> str:
    counts = {s: sum(1 for r in rows if r.status == s) for s in ("pass", "fail", "not run")}
    verdict = "PASS" if passed(rows) else "FAIL"
    return f"{verdict} ({counts['pass']} passed, {counts['fail']} failed, {counts['not run']} not run)"


def render_markdown(rows: Sequence[Row], links: Mapping[str, str], title: str) -> str:
    """The table for a GitHub job summary: a heading with the verdict, the metrics, then the experiments."""
    result = {"pass": "PASS", "fail": "**FAIL**"}
    lines = [f"### {title}: {_verdict(rows)}", "", "| metric | target | observed | examples | result |", "|---|---|---|---|---|"]
    lines += [
        f"| {r.metric} | {_target(r.threshold)} | {_observed(r)} | {r.examples} | {result.get(r.status, r.status)} |"
        for r in rows
    ]
    if links:
        lines += ["", "Experiments:", ""]
        lines += [f"- [{name}]({url})" if url.startswith("http") else f"- {name}: {url}" for name, url in links.items()]
    return "\n".join(lines)
```

and in `render` replace the counts/verdict lines with `lines += ["", f"Gate: {_verdict(rows)}"]`.

- [ ] **Step 4:** gate tests pass.

- [ ] **Step 5: Failing runner tests** in `test_run.py`:

```python
def test_a_summary_file_gets_the_markdown_table(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    code = main(
        ["--split", "smoke", "--summary", str(summary)], client=FakeLangSmith(), suites=_suites(0.5), load=lambda key: ASK
    )
    text = summary.read_text(encoding="utf-8")
    assert code == 1
    assert text.startswith("earlier step\n")  # appended, never overwritten
    assert "### Smoke evals: FAIL" in text
    assert "(https://smith.example/smart-tutor-ask-smoke-1)" in text


def test_a_run_that_stops_early_says_why_in_the_summary(tmp_path: Path) -> None:
    class NoKey(FakeLangSmith):
        def has_dataset(self, *, dataset_name: str) -> bool:
            raise LangSmithError("Authentication failed")

    summary = tmp_path / "summary.md"
    code = main(["--split", "smoke", "--summary", str(summary)], client=NoKey(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    assert "LANGSMITH_API_KEY" in summary.read_text(encoding="utf-8")
```

Add a third for "nothing ran" (`--split full`): the summary contains "Nothing ran".

- [ ] **Step 6:** run → FAIL (unknown argument `--summary`).

- [ ] **Step 7: Implement** in `run.py`: `parser.add_argument("--summary", type=Path, help="append the gate table as Markdown to this file (GitHub's $GITHUB_STEP_SUMMARY)")`. A helper

```python
def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
```

Title: `f"{args.split.capitalize()} evals"`. Every early `return 1` that prints a "Can't …" / "Nothing ran" message also appends it (as `**<message>**`) to the summary; the success path appends `render_markdown(rows, links, title)` (and the "Nothing ran" line after the table when nothing ran). Update the module docstring's Usage line with `[--summary PATH]`.

- [ ] **Step 8:** `cd backend && uv run pytest tests/unit/evals -q` → PASS; then the full backend checks (Global Constraints).

- [ ] **Step 9:** README "Run a split": one sentence — `--summary PATH` appends the table as Markdown (CI passes `$GITHUB_STEP_SUMMARY`); CI runs the smoke split on PRs that change the agent (`.github/workflows/evals-smoke.yml`, see `docs/runbooks/evals-ci.md`).

- [ ] **Step 10: Commit** `Write the gate table as Markdown to a job summary`.

### Task 2: Bedrock-only role for CI evals, documented and checked

**Files:**
- Modify: `infra/smart_tutor_infra/models.py` (add `JUDGE_MODEL = "qwen.qwen3-32b-v1:0"`, docstring mentions the CI evals role)
- Modify: `infra/tests/test_models.py` (judge model in config)
- Create: `docs/runbooks/evals-ci-bedrock-policy.json`, `docs/runbooks/evals-ci-trust-policy.json`, `docs/runbooks/evals-ci.md`
- Create: `infra/tests/test_evals_ci_access.py`

**Interfaces:**
- Produces: role name `smart-tutor-evals-ci`, variable `EVALS_AWS_ROLE_ARN`, secret `LANGSMITH_API_KEY`, project `smart-tutor-ci` (Task 3's workflow names them).

- [ ] **Step 1: Failing tests** `infra/tests/test_evals_ci_access.py`:

```python
"""The CI evals role (#226): Bedrock invoke on exactly the models the evals call, trusted only for this repository's
pull requests and branch runs."""

import json
from pathlib import Path

from smart_tutor_infra.models import AGENT_MODEL, AGENT_MODEL_REGIONS, AGENT_PROFILE, EMBEDDING_MODEL, JUDGE_MODEL
from tests.test_synth import CDK_CONTEXT

RUNBOOKS = Path(__file__).parents[2] / "docs/runbooks"


def policy(name: str) -> dict:
    return json.loads((RUNBOOKS / name).read_text(encoding="utf-8"))


def test_the_role_may_only_invoke_the_models_the_evals_call() -> None:
    (statement,) = policy("evals-ci-bedrock-policy.json")["Statement"]
    assert statement["Effect"] == "Allow"
    assert sorted(statement["Action"]) == ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    assert sorted(statement["Resource"]) == sorted([
        f"arn:aws:bedrock:us-east-1:ACCOUNT_ID:inference-profile/{AGENT_PROFILE}",
        *(f"arn:aws:bedrock:{r}::foundation-model/{AGENT_MODEL}" for r in AGENT_MODEL_REGIONS),
        f"arn:aws:bedrock:us-east-1::foundation-model/{EMBEDDING_MODEL}",
        f"arn:aws:bedrock:us-east-1::foundation-model/{JUDGE_MODEL}",
    ])


def test_the_role_trusts_only_this_repositorys_pull_requests_and_branches() -> None:
    (statement,) = policy("evals-ci-trust-policy.json")["Statement"]
    prefix = CDK_CONTEXT["smart-tutor:github-oidc-subject-prefix"]
    assert statement["Principal"] == {
        "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
    }
    assert statement["Action"] == "sts:AssumeRoleWithWebIdentity"
    assert statement["Condition"]["StringEquals"] == {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"}
    assert sorted(statement["Condition"]["StringLike"]["token.actions.githubusercontent.com:sub"]) == sorted(
        [f"{prefix}:pull_request", f"{prefix}:ref:refs/heads/*"]
    )


def test_the_runbook_names_the_workflow_the_variable_and_the_secret() -> None:
    text = (RUNBOOKS / "evals-ci.md").read_text(encoding="utf-8")
    for name in ("evals-smoke.yml", "EVALS_AWS_ROLE_ARN", "LANGSMITH_API_KEY", "smart-tutor-ci",
                 "evals-ci-bedrock-policy.json", "evals-ci-trust-policy.json", "smart-tutor-evals-ci"):
        assert name in text, name
```

And in `test_models.py` add `assert f'"{JUDGE_MODEL}"' in text`.

- [ ] **Step 2:** `cd infra && uv run pytest tests/test_evals_ci_access.py tests/test_models.py -q` → FAIL.

- [ ] **Step 3:** Add `JUDGE_MODEL` to `models.py`. Write the two JSON files exactly matching the tests (`ACCOUNT_ID` placeholder; `Version: "2012-10-17"`; `Sid` `InvokeEvalModels` / `GitHubEvalsSmoke`).

- [ ] **Step 4:** Write `docs/runbooks/evals-ci.md`: what the job does and when it runs; why a separate role (Bedrock only, no deploy rights; the deploy roles trust only their environments); a bash block to create it (assumes the account's GitHub OIDC provider exists, created by native-cloud's `GitHubDeploy` stack, ADR 0016):

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" docs/runbooks/evals-ci-trust-policy.json > /tmp/trust.json
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" docs/runbooks/evals-ci-bedrock-policy.json > /tmp/bedrock.json
aws iam create-role --role-name smart-tutor-evals-ci --max-session-duration 3600 \
  --assume-role-policy-document file:///tmp/trust.json --description "GitHub Actions smoke evals: Bedrock invoke only (#226)"
aws iam put-role-policy --role-name smart-tutor-evals-ci --policy-name bedrock-invoke --policy-document file:///tmp/bedrock.json
gh variable set EVALS_AWS_ROLE_ARN --repo konica/agent-tutor --body "arn:aws:iam::$ACCOUNT_ID:role/smart-tutor-evals-ci"
gh secret set LANGSMITH_API_KEY --repo konica/agent-tutor   # paste a key for the smart-tutor-ci project's workspace
```

Also: the LangSmith project `smart-tutor-ci` (created on first trace); what a fork PR sees (skip notice; a maintainer can push the branch to this repository or run it from the Actions tab); updating the policy when a model changes (`put-role-policy` again; `infra/tests/test_evals_ci_access.py` fails until the JSON matches); cost note (each run ingests 4 seed PDFs and asks ~10 questions; Bedrock and LangSmith usage only, cancelled when a newer commit is pushed). If no provider exists, show `aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com`.

- [ ] **Step 5:** infra tests pass (`cd infra && uv run pytest -q`).

- [ ] **Step 6: Commit** `Document the Bedrock-only role CI evals sign in with`.

### Task 3: Workflow and Compose override

**Files:**
- Create: `compose.ci.yaml`, `.github/workflows/evals-smoke.yml`
- Modify: `infra/tests/test_workflows.py` (new section "Smoke evals")
- Modify: `sdd/prd.md` (v2.45: §10.3 item 6 wording + change row), `AGENTS.md` (Tests and evals bullet: CI runs the smoke split on agent PRs), `Makefile` none.

**Interfaces:**
- Consumes: `evals.run --summary PATH` (Task 1); `EVALS_AWS_ROLE_ARN`, `LANGSMITH_API_KEY`, `smart-tutor-ci` (Task 2).

- [ ] **Step 1: Failing workflow tests** appended to `infra/tests/test_workflows.py`:

```python
# --- Smoke evals (#226) ------------------------------------------------------------------------------------------

EVAL_PATHS = {
    "backend/src/smart_tutor/tutoring/**",
    "backend/src/smart_tutor/apps/agent/**",
    "backend/src/smart_tutor/apps/mcp_server/**",
    "backend/src/smart_tutor/shared/config.py",
    "backend/src/smart_tutor/shared/adapters/model_factory.py",
    "backend/src/smart_tutor/shared/adapters/bedrock/**",
    "backend/evals/**",
    "compose.yaml",
    "compose.ci.yaml",
    ".github/workflows/evals-smoke.yml",
}


def evals_job() -> dict[str, Any]:
    return only_job("evals-smoke.yml")


def test_smoke_evals_run_on_agent_changes_and_by_hand() -> None:
    on = workflow("evals-smoke.yml")["on"]
    assert set(on) == {"pull_request", "workflow_dispatch"}
    assert set(on["pull_request"]["paths"]) == EVAL_PATHS
    # a newer push cancels the run it replaces
    assert workflow("evals-smoke.yml")["concurrency"]["cancel-in-progress"] is True


def test_smoke_evals_sign_in_with_the_bedrock_only_role() -> None:
    wf, job = workflow("evals-smoke.yml"), evals_job()
    assert wf["permissions"] == {"contents": "read"}
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    creds = step(job, "Sign in to AWS (Bedrock only)")
    assert creds["with"] == {"role-to-assume": "${{ vars.EVALS_AWS_ROLE_ARN }}", "aws-region": "us-east-1"}
    assert job["timeout-minutes"] <= 60  # the role's session lasts 1 hour
    for ref in (str(s["uses"]) for s in job["steps"] if "uses" in s):
        assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", ref), ref
    creds_at = index_of(job, "configure-aws-credentials")
    assert index_of(job, "setup-uv") < creds_at
    assert index_of(job, "compose.ci.yaml --profile app build") < creds_at  # build without credentials


def test_smoke_evals_skip_with_a_reason_without_the_secrets() -> None:
    job = evals_job()
    check = step(job, "Check access to the eval secrets")
    assert check["id"] == "access"
    assert job["steps"].index(check) < index_of(job, "configure-aws-credentials")
    script = check["run"]
    assert "GITHUB_STEP_SUMMARY" in script and "::notice" in script and "::warning" in script
    assert "fork" in script and "docs/runbooks/evals-ci.md" in script
    for s in job["steps"][job["steps"].index(check) + 1 :]:
        assert "steps.access.outputs.run == 'true'" in str(s.get("if", "")), s.get("name") or s.get("uses")


def test_smoke_evals_skip_script_decides_correctly(tmp_path: Path) -> None:
    if shutil.which("bash") is None:
        pytest.skip("bash is not installed")
    script = step(evals_job(), "Check access to the eval secrets")["run"]

    def run(**env: str) -> tuple[str, str]:
        out, summary = tmp_path / "out", tmp_path / "summary"
        out.write_text(""), summary.write_text("")
        result = subprocess.run(
            ["bash", "-c", script],
            env={"PATH": os.environ["PATH"], "GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary), **env},
            capture_output=True, text=True, check=True,
        )
        return out.read_text() + summary.read_text(), result.stdout

    files, stdout = run(HEAD_REPO="someone/agent-tutor", REPO="konica/agent-tutor", ROLE="", HAS_KEY="false")
    assert "run=false" in files and "fork" in files and "::notice" in stdout
    files, stdout = run(HEAD_REPO="konica/agent-tutor", REPO="konica/agent-tutor", ROLE="", HAS_KEY="true")
    assert "run=false" in files and "EVALS_AWS_ROLE_ARN" in files and "::warning" in stdout
    files, stdout = run(HEAD_REPO="konica/agent-tutor", REPO="konica/agent-tutor", ROLE="arn:x", HAS_KEY="false")
    assert "run=false" in files and "LANGSMITH_API_KEY" in files
    files, _ = run(HEAD_REPO="", REPO="konica/agent-tutor", ROLE="arn:x", HAS_KEY="true")  # workflow_dispatch
    assert "run=true" in files


def test_smoke_evals_load_the_learners_then_gate_into_the_summary() -> None:
    job = evals_job()
    assert index_of(job, "configure-aws-credentials") < index_of(job, "compose.ci.yaml --profile app up")
    assert index_of(job, "compose.ci.yaml --profile app up") < index_of(job, "evals.learners")
    gate = step(job, "Run the smoke split")
    assert index_of(job, "evals.learners") < job["steps"].index(gate)
    assert "--split smoke" in gate["run"] and '--summary "$GITHUB_STEP_SUMMARY"' in gate["run"]
    assert gate["env"]["LANGSMITH_API_KEY"] == "${{ secrets.LANGSMITH_API_KEY }}"
    assert "smart-tutor-ci" in step(job, "Prepare .env")["run"]
    for s in job["steps"]:
        assert "${{" not in str(s.get("run", "")), s.get("name")


def test_ci_compose_override_passes_the_oidc_session_not_a_profile() -> None:
    override = yaml.safe_load((WORKFLOWS.parents[1] / "compose.ci.yaml").read_text(encoding="utf-8"))
    for service in ("api", "agent", "mcp", "worker"):
        env = override["services"][service]["environment"]
        assert {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "LANGSMITH_API_KEY"} <= set(env), service
    assert "AWS_PROFILE" in step(evals_job(), "Prepare .env")["run"]  # removed, so botocore uses the session
```

Add `import os` at the top of the test module.

- [ ] **Step 2:** `cd infra && uv run pytest tests/test_workflows.py -q -k smoke_evals or ci_compose` → FAIL (file missing).

- [ ] **Step 3: `compose.ci.yaml`** at the repo root:

```yaml
# CI override for the smoke evals (.github/workflows/evals-smoke.yml, #226):
#   docker compose -f compose.yaml -f compose.ci.yaml --profile app up -d
# GitHub signs in to AWS with OIDC, which puts a short-lived session in the runner's environment instead of a profile
# in ~/.aws. Pass it, and the LangSmith key, through to the services that call Bedrock; a name without a value takes
# the runner's variable. The api and worker still sign LocalStack calls with its dummy keys (SMART_TUTOR_LOCALSTACK).
x-ci-env: &ci-env
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_SESSION_TOKEN
  - LANGSMITH_API_KEY

services:
  api: {environment: *ci-env}
  agent: {environment: *ci-env}
  mcp: {environment: *ci-env}
  worker: {environment: *ci-env}
```

Caveat to verify: Compose merges a list-form `environment` with the base map-form one (it does: entries are merged by name). Verify with `docker compose -f compose.yaml -f compose.ci.yaml --profile app config` that each service keeps its base variables and gains the four names.

- [ ] **Step 4: `.github/workflows/evals-smoke.yml`:**

```yaml
# Runs the smoke split (PRD §10.3, #226) on pull requests that change the agent, and by hand from the Actions tab:
# starts the Compose app stack, loads the eval learners' libraries, and gates on thresholds.yaml. The gate table and
# the experiment link go to the job summary; a breached threshold fails the check.
# Needs the repository variable EVALS_AWS_ROLE_ARN (a Bedrock-only role trusted through GitHub OIDC) and the secret
# LANGSMITH_API_KEY (docs/runbooks/evals-ci.md). Without them (a fork, Dependabot, or before they exist) the job skips
# and says why.
name: evals-smoke

on:
  pull_request:
    paths:
      - backend/src/smart_tutor/tutoring/**
      - backend/src/smart_tutor/apps/agent/**
      - backend/src/smart_tutor/apps/mcp_server/**
      - backend/src/smart_tutor/shared/config.py
      - backend/src/smart_tutor/shared/adapters/model_factory.py
      - backend/src/smart_tutor/shared/adapters/bedrock/**
      - backend/evals/**
      - compose.yaml
      - compose.ci.yaml
      - .github/workflows/evals-smoke.yml
  workflow_dispatch:

permissions:
  contents: read

# One run per pull request (or branch); a newer push cancels the run it replaces.
concurrency:
  group: evals-smoke-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: true

jobs:
  smoke:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    timeout-minutes: 60  # the role's session lasts 1 hour
    steps:
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0

      # Forks and Dependabot get neither secrets nor an OIDC token: skip with a reason instead of failing.
      - name: Check access to the eval secrets
        id: access
        env:
          HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}
          REPO: ${{ github.repository }}
          ROLE: ${{ vars.EVALS_AWS_ROLE_ARN }}
          HAS_KEY: ${{ secrets.LANGSMITH_API_KEY != '' }}
        run: |
          skip() {
            echo "::$1 title=Smoke evals skipped::$2"
            printf '### Smoke evals skipped\n\n%s\n' "$2" >> "$GITHUB_STEP_SUMMARY"
            echo "run=false" >> "$GITHUB_OUTPUT"
            exit 0
          }
          if [[ -n "$HEAD_REPO" && "$HEAD_REPO" != "$REPO" ]]; then
            skip notice "This pull request comes from a fork, which can't use the eval role or the LangSmith key. A maintainer can push its branch to $REPO, or run evals-smoke on such a branch from the Actions tab."
          fi
          [[ -n "$ROLE" ]] || skip warning "The repository variable EVALS_AWS_ROLE_ARN isn't set (docs/runbooks/evals-ci.md)."
          [[ "$HAS_KEY" == true ]] || skip warning "The secret LANGSMITH_API_KEY isn't available to this run (not set, or a Dependabot pull request; docs/runbooks/evals-ci.md)."
          echo "run=true" >> "$GITHUB_OUTPUT"

      - uses: astral-sh/setup-uv@d0cc045d04ccac9d8b7881df0226f9e82c39688e # v6.8.0
        if: steps.access.outputs.run == 'true'

      # The local defaults, minus the developer profile: botocore then uses the OIDC session from the environment.
      - name: Prepare .env
        if: steps.access.outputs.run == 'true'
        run: |
          grep -v '^AWS_PROFILE=' .env.example | sed 's/^LANGSMITH_PROJECT=.*/LANGSMITH_PROJECT=smart-tutor-ci/' > .env
          mkdir -p ~/.aws  # compose.yaml mounts it; an empty folder, not one Docker creates as root

      - name: Install the eval dependencies
        if: steps.access.outputs.run == 'true'
        working-directory: backend
        run: uv sync --frozen --extra eval

      - name: Build the app images
        if: steps.access.outputs.run == 'true'
        run: docker compose -f compose.yaml -f compose.ci.yaml --profile app build

      - name: Sign in to AWS (Bedrock only)
        if: steps.access.outputs.run == 'true'
        uses: aws-actions/configure-aws-credentials@7474bc4690e29a8392af63c5b98e7449536d5c3a # v4.3.1
        with:
          role-to-assume: ${{ vars.EVALS_AWS_ROLE_ARN }}
          aws-region: us-east-1

      - name: Start the stack
        if: steps.access.outputs.run == 'true'
        env:
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        run: |
          docker compose -f compose.yaml -f compose.ci.yaml --profile app up -d
          wait_for() {
            for _ in $(seq 90); do curl -fs -o /dev/null "$1" && return 0; sleep 2; done
            echo "::error::$1 didn't answer within 3 minutes"; return 1
          }
          wait_for http://localhost:10450/healthz
          wait_for http://localhost:10401/realms/smart-tutor
          wait_for http://localhost:10451/healthz

      - name: Load the eval learners' libraries
        if: steps.access.outputs.run == 'true'
        working-directory: backend
        run: uv run --extra eval python -m evals.learners

      - name: Run the smoke split
        if: steps.access.outputs.run == 'true'
        working-directory: backend
        env:
          LANGSMITH_API_KEY: ${{ secrets.LANGSMITH_API_KEY }}
        run: uv run --env-file ../.env --extra eval python -m evals.run --split smoke --summary "$GITHUB_STEP_SUMMARY"

      - name: Service logs
        if: failure() && steps.access.outputs.run == 'true'
        run: docker compose -f compose.yaml -f compose.ci.yaml --profile app logs --no-color --tail 200 api worker agent mcp
```

Notes for the implementer: keep the literal `compose.ci.yaml --profile app build` / `up` strings the tests look for. The MCP server has no health route; the agent's `/healthz` starts after the agent, which depends on mcp being started. Confirm `curl -fs http://localhost:10451/healthz` is the agent route (`apps/agent/server.py:151`).

- [ ] **Step 5:** `cd infra && uv run pytest -q` → PASS (including `test_every_workflow_run_script_is_valid_bash`).

- [ ] **Step 6: Docs.** PRD: bump status to v2.45 and add a change row at the top ("Smoke evals in CI (#226, §10.3): the smoke split runs on pull requests that change the agent (tutoring, the agent and MCP apps, model settings, the evals) and by hand, with a Bedrock-only role through GitHub OIDC and traces in `smart-tutor-ci`; forks skip it. No product behavior changes."); §10.3 item 6 → "versioned splits (smoke ~30 items on every PR that changes the agent; full before release)". AGENTS.md "Tests and evals": add "CI runs the smoke split on PRs that change the agent (`.github/workflows/evals-smoke.yml`, `docs/runbooks/evals-ci.md`)."

- [ ] **Step 7: Commit** `Run the smoke split in CI on pull requests that change the agent`.
