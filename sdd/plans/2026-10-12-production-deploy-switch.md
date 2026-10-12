# Production Deploy Switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One repository variable, `PRODUCTION_DEPLOY`, turns every production deploy (merge, manual run, rollback, image build) on or off in both deployment modes (#282).

**Architecture:** The three reusable workflows that enter a production environment (`build-images.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`) get a job-level `if: vars.PRODUCTION_DEPLOY == 'true'`. That's the only enforcement point, so every caller is covered. `deploy.yml` and `rollback.yml` get a `production-switch` job that reports the state. When the switch is off, it posts a notice on a push and fails a manual or rollback run. The teardown script and the docs learn about the switch.

**Tech Stack:** GitHub Actions YAML, bash (run scripts), PowerShell 7 (teardown script), pytest + PyYAML static workflow tests in `infra/tests/test_workflows.py` (run with `cd infra && uv run pytest`).

**Spec:** `sdd/specs/2026-10-12-production-deploy-switch-design.md`

## Global Constraints

- Variable name `PRODUCTION_DEPLOY`. It is a **repository** variable, not an environment variable.
- Only `true` deploys. GitHub's `==` ignores case in expressions, so the bash check lowercases (`${SWITCH,,}`) to agree. Unset, empty, or any other value means off (fail closed).
- The enforcement expression is exactly `vars.PRODUCTION_DEPLOY == 'true'`. It never uses `!=`.
- `ON_PREMISE_IF` and `NATIVE_CLOUD_IF` in `deploy.yml` stay byte-for-byte unchanged. Rollback's `if:` lines stay unchanged.
- `ci.yml` and the `checks` job are untouched; CI runs whatever the switch says.
- No AWS or CDK change.
- Every job in `deploy.yml`/`rollback.yml` that does not call an environment workflow has `permissions: {contents: read}` and no `secrets` (existing test `test_only_main_and_rollback_reach_the_deploy_environments`).
- Run summary text, exactly: ON → `Production deploys are ON (PRODUCTION_DEPLOY=true).`; OFF → `Production deploys are OFF (PRODUCTION_DEPLOY is not true). Nothing was deployed.`
- PRD goes from v2.52 to v2.53 (status line, a new "Changes from v2.52" row, and the version in `AGENTS.md`).
- Commit subjects in the imperative mood; the body says why. End each commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. `PRODUCTION_DEPLOY=True` or `TRUE`: deploys. Expressions ignore case, and the report script must agree, so it says ON (Task 1 test).
2. `PRODUCTION_DEPLOY=" true"` (stray space) or `yes`: off in both the expression and the report (Task 1 test).
3. A rollback with the switch off: the run fails red, not a green run with skipped jobs (Task 1 test, `workflow_dispatch` case).
4. A future workflow that calls an environment workflow without a `production-switch` job: the contract test fails (Task 1 test).
5. Teardown while `NATIVE_CLOUD_AUTO_DEPLOY=true` but `PRODUCTION_DEPLOY` is not `true`: the preflight passes, because no merge deploys anything (Task 2 test).

---

### Task 1: Enforce and report the switch in the workflows

**Files:**
- Modify: `.github/workflows/build-images.yml` (header comment lines 1-6; job `build` at line 22)
- Modify: `.github/workflows/deploy-on-premise.yml` (header lines 1-4; job `deploy` at line 20)
- Modify: `.github/workflows/deploy-native-cloud.yml` (header lines 1-5; job `deploy` at line 21)
- Modify: `.github/workflows/deploy.yml` (header lines 1-8; new job after `checks`)
- Modify: `.github/workflows/rollback.yml` (header lines 1-4; new job before `on-premise`)
- Test: `infra/tests/test_workflows.py`

**Interfaces:**
- Consumes: the helpers `workflow(name)`, `only_job(name)`, `step(job, name)`, the constants `WORKFLOWS`, `ENVIRONMENT_WORKFLOWS`, `ON_PREMISE_IF` and `NATIVE_CLOUD_IF`, all already in `infra/tests/test_workflows.py`.
- Produces: the job id `production-switch` in `deploy.yml` and `rollback.yml`; its step name `Report the production deploy switch`; the constant `PRODUCTION_SWITCH_IF = "vars.PRODUCTION_DEPLOY == 'true'"` in the test module. Task 3's docs refer to the run-summary wording above.

- [ ] **Step 1: Write the failing tests**

Add this block to `infra/tests/test_workflows.py` right after `test_rollback_redeploys_the_chosen_mode_without_infrastructure` (before the `# --- build-images.yml ---` comment):

```python
# --- The production deploy switch (#282) -----------------------------------------------------------------------

# Only `true` deploys (case-insensitive in expressions); unset or anything else stops every production deploy.
PRODUCTION_SWITCH_IF = "vars.PRODUCTION_DEPLOY == 'true'"
SWITCH_STEP = "Report the production deploy switch"


def test_every_job_that_enters_a_production_environment_needs_the_switch() -> None:
    for name in ENVIRONMENT_WORKFLOWS:
        job = only_job(name)
        assert job["if"] == PRODUCTION_SWITCH_IF, name
        assert "!=" not in job["if"], name  # fail closed: unset must not deploy


def test_the_switch_leaves_the_per_mode_conditions_alone() -> None:
    jobs = workflow("deploy.yml")["jobs"]
    for mode, condition in (("on-premise", ON_PREMISE_IF), ("native-cloud", NATIVE_CLOUD_IF)):
        assert jobs[f"images-{mode}"]["if"] == condition
        assert jobs[mode]["if"] == condition
    assert "PRODUCTION_DEPLOY" not in str(workflow("ci.yml"))


def test_every_caller_of_a_production_workflow_reports_the_switch() -> None:
    # A new workflow that calls an environment workflow fails here until it reports the switch too.
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = workflow(path.name)["jobs"]
        calls = [j for j in jobs.values() if j.get("uses", "").removeprefix("./.github/workflows/") in ENVIRONMENT_WORKFLOWS]
        if not calls:
            continue
        report = jobs["production-switch"]
        assert report["permissions"] == {"contents": "read"}, path.name
        assert "needs" not in report and "uses" not in report, path.name
        assert step(report, SWITCH_STEP)["env"] == {
            "SWITCH": "${{ vars.PRODUCTION_DEPLOY }}",
            "EVENT": "${{ github.event_name }}",
        }, path.name
    assert step(workflow("deploy.yml")["jobs"]["production-switch"], SWITCH_STEP)["run"] == step(
        workflow("rollback.yml")["jobs"]["production-switch"], SWITCH_STEP
    )["run"]


def test_the_switch_is_named_in_the_workflow_headers() -> None:
    for name in ("deploy.yml", "rollback.yml", *ENVIRONMENT_WORKFLOWS):
        header = (WORKFLOWS / name).read_text(encoding="utf-8").split("\nname: ")[0]
        assert "PRODUCTION_DEPLOY" in header, name


def test_the_switch_report_decides_correctly(tmp_path: Path) -> None:
    bash = shutil.which("bash")  # the full path: on Windows a bare "bash" can reach the WSL launcher in System32
    if bash is None:
        pytest.skip("bash is not installed")
    script = step(workflow("deploy.yml")["jobs"]["production-switch"], SWITCH_STEP)["run"]

    def run(switch: str, event: str) -> tuple[int, str, str]:
        summary = tmp_path / "summary"
        summary.write_text("")
        result = subprocess.run(
            [bash, "-c", script],
            env={"PATH": os.environ["PATH"], "GITHUB_STEP_SUMMARY": str(summary), "SWITCH": switch, "EVENT": event},
            capture_output=True, text=True, check=False,
        )
        return result.returncode, result.stdout, summary.read_text()

    for on in ("true", "True", "TRUE"):
        code, stdout, summary = run(on, "workflow_dispatch")
        assert code == 0 and "Production deploys are ON (PRODUCTION_DEPLOY=true)." in summary, on
        assert "::" not in stdout, on
    off = "Production deploys are OFF (PRODUCTION_DEPLOY is not true). Nothing was deployed."
    for value in ("", "false", " true", "yes"):
        code, stdout, summary = run(value, "push")
        assert code == 0 and "::notice" in stdout and off in summary, repr(value)
        code, stdout, summary = run(value, "workflow_dispatch")  # a manual deploy or any rollback
        assert code == 1 and "::error" in stdout and off in summary, repr(value)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd infra && uv run pytest tests/test_workflows.py -k "switch" -v`
Expected: these fail:
- `test_every_job_that_enters_a_production_environment_needs_the_switch` (`KeyError: 'if'`);
- `test_every_caller_of_a_production_workflow_reports_the_switch` (`KeyError: 'production-switch'`);
- `test_the_switch_is_named_in_the_workflow_headers`;
- `test_the_switch_report_decides_correctly`.

`test_the_switch_leaves_the_per_mode_conditions_alone` passes already.

- [ ] **Step 3: Gate the three environment workflows**

In `.github/workflows/build-images.yml`, change the job opening from:

```yaml
jobs:
  build:
    runs-on: ubuntu-latest
```
to:
```yaml
jobs:
  build:
    # The production deploy switch (#282): only `true` builds and pushes; this job also deploys the Registry stack.
    if: vars.PRODUCTION_DEPLOY == 'true'
    runs-on: ubuntu-latest
```
and append this line to its header comment (after line 6, before `name: build-images`):
```yaml
# Skipped unless the repository variable PRODUCTION_DEPLOY is `true` (#282).
```

In `.github/workflows/deploy-on-premise.yml`, change:
```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: on-premise
```
to:
```yaml
jobs:
  deploy:
    # The production deploy switch (#282): skipped unless PRODUCTION_DEPLOY is `true`, whoever calls it.
    if: vars.PRODUCTION_DEPLOY == 'true'
    runs-on: ubuntu-latest
    environment: on-premise
```
and append to its header comment (before `name: deploy-on-premise`):
```yaml
# Skipped unless the repository variable PRODUCTION_DEPLOY is `true` (#282).
```

In `.github/workflows/deploy-native-cloud.yml`, change:
```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: native-cloud
```
to:
```yaml
jobs:
  deploy:
    # The production deploy switch (#282): skipped unless PRODUCTION_DEPLOY is `true`, whoever calls it.
    if: vars.PRODUCTION_DEPLOY == 'true'
    runs-on: ubuntu-latest
    environment: native-cloud
```
and append to its header comment (before `name: deploy-native-cloud`):
```yaml
# Skipped unless the repository variable PRODUCTION_DEPLOY is `true` (#282).
```

- [ ] **Step 4: Add the report job to deploy.yml and rollback.yml**

In `.github/workflows/deploy.yml`, replace the header line
```yaml
# Runbooks: docs/runbooks/on-premise-deploy.md, docs/runbooks/pilot-deploy.md (native-cloud).
```
with
```yaml
# Nothing deploys unless the repository variable PRODUCTION_DEPLOY is `true` (#282): build-images.yml and both deploy
# workflows skip their job otherwise, and the production-switch job reports it (a notice on a push, an error on a run by
# hand). The per-mode variables above choose what deploys only while it is on.
# Runbooks: docs/runbooks/on-premise-deploy.md, docs/runbooks/pilot-deploy.md (native-cloud).
```
and insert this job between `checks` and the `# Each mode's images go to ...` comment:

```yaml
  # Reports the production deploy switch (#282). The environment workflows enforce it; this job only makes it visible.
  production-switch:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Report the production deploy switch
        env:
          SWITCH: ${{ vars.PRODUCTION_DEPLOY }}
          EVENT: ${{ github.event_name }}
        run: |
          if [ "${SWITCH,,}" = true ]; then
            echo "Production deploys are ON (PRODUCTION_DEPLOY=true)." >> "$GITHUB_STEP_SUMMARY"
            exit 0
          fi
          msg="Production deploys are OFF (PRODUCTION_DEPLOY is not true). Nothing was deployed."
          echo "$msg" >> "$GITHUB_STEP_SUMMARY"
          if [ "$EVENT" = push ]; then echo "::notice title=Production deploys off::$msg"; exit 0; fi
          echo "::error title=Production deploys off::$msg"
          exit 1

```

In `.github/workflows/rollback.yml`, replace the header line
```yaml
# The deploy environments only accept runs from main: start it from main with the SHA to go back to.
```
with
```yaml
# The deploy environments only accept runs from main: start it from main with the SHA to go back to.
# Nothing is redeployed unless the repository variable PRODUCTION_DEPLOY is `true` (#282); the run then fails and says so.
```
and insert the same job as the first job under `jobs:`:

```yaml
  # Reports the production deploy switch (#282). The environment workflows enforce it; this job only makes it visible.
  production-switch:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - name: Report the production deploy switch
        env:
          SWITCH: ${{ vars.PRODUCTION_DEPLOY }}
          EVENT: ${{ github.event_name }}
        run: |
          if [ "${SWITCH,,}" = true ]; then
            echo "Production deploys are ON (PRODUCTION_DEPLOY=true)." >> "$GITHUB_STEP_SUMMARY"
            exit 0
          fi
          msg="Production deploys are OFF (PRODUCTION_DEPLOY is not true). Nothing was deployed."
          echo "$msg" >> "$GITHUB_STEP_SUMMARY"
          if [ "$EVENT" = push ]; then echo "::notice title=Production deploys off::$msg"; exit 0; fi
          echo "::error title=Production deploys off::$msg"
          exit 1

```

- [ ] **Step 5: Run the workflow tests to verify they pass**

Run: `cd infra && uv run pytest tests/test_workflows.py -v`
Expected: all pass. That includes the existing `test_only_main_and_rollback_reach_the_deploy_environments` (the new job is a non-caller with `contents: read` and no `secrets`) and `test_every_workflow_run_script_is_valid_bash`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/build-images.yml .github/workflows/deploy-on-premise.yml .github/workflows/deploy-native-cloud.yml .github/workflows/deploy.yml .github/workflows/rollback.yml infra/tests/test_workflows.py
git commit -m "Stop every production deploy unless PRODUCTION_DEPLOY is true" -m "The repository is public and the PO wants one setting that stops all production changes (#282). The three workflows that enter a production environment now skip their job unless the repository variable PRODUCTION_DEPLOY is true, so merges, manual runs, rollbacks, and image builds all stop; deploy.yml and rollback.yml report the state (a notice on a push, an error on a run by hand)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Teach the native-cloud teardown preflight about the switch

**Files:**
- Modify: `docs/runbooks/pilot-teardown.ps1:7-8` (help text) and `:158-169` (preflight)
- Modify: `docs/runbooks/pilot-teardown.md:26-32` (section 3)
- Test: `infra/tests/test_workflows.py`

**Interfaces:**
- Consumes: the constant `RUNBOOKS` in the test module.
- Produces: the variable `$ProductionDeploy` in the script (nothing else depends on it).

- [ ] **Step 1: Write the failing test**

Add after `test_native_cloud_teardown_runbook_leaves_on_premise_alone` in `infra/tests/test_workflows.py`:

```python
def test_native_cloud_teardown_stops_only_when_a_merge_would_redeploy() -> None:
    # A merge redeploys native-cloud only while both the production switch and the native-cloud variable are `true`.
    script = (RUNBOOKS / "pilot-teardown.ps1").read_text(encoding="utf-8")
    assert "$ProductionDeploy = gh variable get PRODUCTION_DEPLOY --repo $Repo 2>$null" in script
    assert 'if ($AutoDeploy -eq "true" -and $ProductionDeploy -eq "true") {' in script
    assert "PRODUCTION_DEPLOY isn't 'true'" in script  # says why it's safe when only the mode variable is on
    runbook = (RUNBOOKS / "pilot-teardown.md").read_text(encoding="utf-8")
    assert "PRODUCTION_DEPLOY" in runbook.split("## 3.")[1].split("## 4.")[0]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd infra && uv run pytest tests/test_workflows.py -k teardown_stops_only -v`
Expected: FAIL on the first assertion.

- [ ] **Step 3: Change the preflight**

In `docs/runbooks/pilot-teardown.ps1`, replace:

```powershell
    # Since #150 deploy.yml deploys native-cloud on a merge only while NATIVE_CLOUD_AUTO_DEPLOY is `true`. The script
    # never changes it: that is a repository setting, so you do it.
    $AutoDeploy = gh variable get NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo 2>$null
    if ($AutoDeploy -eq "true") {
```
with:
```powershell
    # Since #150 deploy.yml deploys native-cloud on a merge only while NATIVE_CLOUD_AUTO_DEPLOY is `true`, and since #282
    # only while the production switch PRODUCTION_DEPLOY is `true` as well. The script never changes either: they are
    # repository settings, so you do it.
    $AutoDeploy = gh variable get NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo 2>$null
    $ProductionDeploy = gh variable get PRODUCTION_DEPLOY --repo $Repo 2>$null
    if ($AutoDeploy -eq "true" -and -not ($ProductionDeploy -eq "true")) {
        Write-Host "NATIVE_CLOUD_AUTO_DEPLOY is 'true', but PRODUCTION_DEPLOY isn't 'true', so no merge deploys anything."
    }
    if ($AutoDeploy -eq "true" -and $ProductionDeploy -eq "true") {
```
The block's body (the `$SetCommand`, `Write-Warning` and `throw` lines) and its closing `}` stay as they are.

In the help text near the top, replace:
```powershell
    1. Preflight: checks the tools, the caller and the repository variable NATIVE_CLOUD_AUTO_DEPLOY (it must not be
```
with:
```powershell
    1. Preflight: checks the tools, the caller and the repository variables NATIVE_CLOUD_AUTO_DEPLOY and PRODUCTION_DEPLOY
       (a merge must not redeploy native-cloud, which needs both to be `true`; NATIVE_CLOUD_AUTO_DEPLOY must not be
```
Read the next help line after it. It continues the old sentence ("`true`) ..."), so check that the two lines together still read as one sentence; adjust only the wording of that continuation if needed.

- [ ] **Step 4: Update the runbook section**

In `docs/runbooks/pilot-teardown.md`, replace:
```markdown
Since #150 native-cloud deploys on a merge only while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`. Make sure it isn't (the script checks it and stops if it is `true`; it never changes it itself):
```
with:
```markdown
Since #150 native-cloud deploys on a merge only while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`, and since #282 only while the production switch `PRODUCTION_DEPLOY` is `true` too. Make sure `NATIVE_CLOUD_AUTO_DEPLOY` isn't `true`. The script checks both and stops only if both are `true`; it never changes either itself:
```

- [ ] **Step 5: Verify**

Run: `cd infra && uv run pytest tests/test_workflows.py -k teardown -v`
Expected: PASS.
Run (PowerShell): `$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("$PWD/docs/runbooks/pilot-teardown.ps1",[ref]$null,[ref]$e); $e.Count`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add docs/runbooks/pilot-teardown.ps1 docs/runbooks/pilot-teardown.md infra/tests/test_workflows.py
git commit -m "Let the native-cloud teardown pass while production deploys are off" -m "Since #282 a merge redeploys native-cloud only when PRODUCTION_DEPLOY and NATIVE_CLOUD_AUTO_DEPLOY are both true, so the preflight stops only in that case and otherwise says why it is safe." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Document the switch (PRD, ADR, runbooks, README)

**Files:**
- Modify: `sdd/prd.md` (line 5 status; new row after line 5; line 536 §9.11 "Deployed" row; §9.12 "**Delivery:**")
- Modify: `AGENTS.md` (the `sdd/prd.md` version in the sources-of-truth table)
- Modify: `sdd/adr/0012-on-premise-default-deployment-mode.md` (status line 3; append a section at the end)
- Modify: `docs/runbooks/on-premise-deploy.md` (line 3; section 3 "What runs." paragraph at line 67; new subsection at the end of section 3; section 8 step 1 at line 285)
- Modify: `docs/runbooks/pilot-deploy.md` (line 262 "What runs.")
- Modify: `README.md` (lines 132-134 under "## Deploy")
- Modify: `docs/architecture/solution-architecture.md` (line 280, step "2. Merge to `main`")
- Test: `infra/tests/test_workflows.py`

**Interfaces:**
- Consumes: the run-summary wording and the job name `production-switch` from Task 1.
- Produces: the runbook heading `### Turn all production deploys off or on (#282)` that other docs link to by name.

- [ ] **Step 1: Write the failing test**

Add after `test_the_on_premise_auto_deploy_switch_is_documented` in `infra/tests/test_workflows.py`:

```python
def test_the_production_deploy_switch_is_documented() -> None:
    root = WORKFLOWS.parents[1]
    for path in (
        RUNBOOKS / "on-premise-deploy.md",
        RUNBOOKS / "pilot-deploy.md",
        RUNBOOKS / "pilot-teardown.md",
        root / "README.md",
        root / "sdd/prd.md",
        root / "sdd/adr/0012-on-premise-default-deployment-mode.md",
        root / "docs/architecture/solution-architecture.md",
    ):
        assert "PRODUCTION_DEPLOY" in path.read_text(encoding="utf-8"), path.name
    text = (RUNBOOKS / "on-premise-deploy.md").read_text(encoding="utf-8")
    section = text.split("### Turn all production deploys off or on (#282)")[1].split("\n## ")[0]
    for phrase in (
        "gh variable set PRODUCTION_DEPLOY --body false --repo konica/agent-tutor",
        "gh variable set PRODUCTION_DEPLOY --body true --repo konica/agent-tutor",
        "Settings → Secrets and variables → Actions → Variables",
        "queued",
        "not a security boundary",
    ):
        assert phrase in section, phrase
    assert "Draft v2.53" in (root / "sdd/prd.md").read_text(encoding="utf-8")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd infra && uv run pytest tests/test_workflows.py -k production_deploy_switch_is_documented -v`
Expected: FAIL (`on-premise-deploy.md` lacks `PRODUCTION_DEPLOY`).

- [ ] **Step 3: PRD and AGENTS.md**

In `sdd/prd.md` line 5, change `Draft v2.52` to `Draft v2.53`. Insert this row directly below line 5 (above `| **Changes from v2.51** |`):

```markdown
| **Changes from v2.52** | Production deploy switch (#282, §9.11, §9.12): the repository variable `PRODUCTION_DEPLOY` turns every production deploy on or off. Only `true` deploys; unset or any other value stops merge deploys, manual deploys, rollbacks, and image builds in both modes, while CI checks still run. Each deploy and rollback run reports it: a notice on a merge, an error on a run by hand. The per-mode variables `ON_PREMISE_AUTO_DEPLOY` and `NATIVE_CLOUD_AUTO_DEPLOY` choose what deploys only while it is on. The repository owner flips it; it is an operating control, not a security boundary. |
```

Replace the §9.11 row:
```markdown
| Deployed | On every merge to `main`, unless `ON_PREMISE_AUTO_DEPLOY=false` (while it is torn down) | By `workflow_dispatch`, or on every merge when `NATIVE_CLOUD_AUTO_DEPLOY=true` |
```
with:
```markdown
| Deployed (only while `PRODUCTION_DEPLOY=true`, §9.12) | On every merge to `main`, unless `ON_PREMISE_AUTO_DEPLOY=false` (while it is torn down) | By `workflow_dispatch`, or on every merge when `NATIVE_CLOUD_AUTO_DEPLOY=true` |
```

In §9.12, replace the line `**Delivery:**` and the blank line after it with:

```markdown
**Delivery:** nothing deploys unless the repository variable `PRODUCTION_DEPLOY` is `true` (#282):

| `PRODUCTION_DEPLOY` | Merge to `main` | Manual deploy | Rollback |
|---|---|---|---|
| not `true` (unset, empty, anything else) | CI checks run; no images, no deploy; the run is green with a notice | The run fails and says so; nothing deployed | The run fails and says so; nothing deployed |
| `true` | The rules below | Deploys the chosen mode | Redeploys the chosen tag |

```

In `AGENTS.md`, change `` `sdd/prd.md` (v2.52) `` to `` `sdd/prd.md` (v2.53) ``.

- [ ] **Step 4: ADR 0012 addendum**

Change line 3 of `sdd/adr/0012-on-premise-default-deployment-mode.md` from
```markdown
- Status: accepted; "ECR is shared" superseded by 0016 (the modes share no stack)
```
to
```markdown
- Status: accepted; "ECR is shared" superseded by 0016 (the modes share no stack); delivery amended 2026-10-12 (production deploy switch)
```
and append at the end of the file:

```markdown

## Addendum 2026-10-12: production deploy switch (#282)

The repository became public. The repository variable `PRODUCTION_DEPLOY` now sits above the delivery rules in this ADR. Only `true` deploys anything. Otherwise no merge deploy, manual deploy, rollback, or image build runs in either mode. It is checked as a job-level `if:` in the three workflows that enter a production environment (`build-images.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`), so every caller is covered. No AWS-side control was added: the deploy roles already trust only the GitHub environments, and a hand-made IAM deny would drift from CDK. It is an operating control, not a security boundary. Design: `sdd/specs/2026-10-12-production-deploy-switch-design.md`.
```

- [ ] **Step 5: on-premise runbook**

In `docs/runbooks/on-premise-deploy.md` line 3, replace
`Every merge to `main` deploys on-premise automatically, unless `ON_PREMISE_AUTO_DEPLOY` is `false` (section 3).`
with
`Every merge to `main` deploys on-premise automatically while the production switch `PRODUCTION_DEPLOY` is `true`, unless `ON_PREMISE_AUTO_DEPLOY` is `false` (section 3).`

In the section 3 "**What runs.**" paragraph:
- Replace its first words `**What runs.** On every push to `main`,` with `**What runs.** While `PRODUCTION_DEPLOY` is `true` (see "Turn all production deploys off or on" below), on every push to `main`,`.
- Replace its last sentence `A run by hand (`gh workflow run deploy.yml -f mode=on-premise`) deploys either way.` with `A run by hand (`gh workflow run deploy.yml -f mode=on-premise`) deploys either way, as long as `PRODUCTION_DEPLOY` is `true`.`

Insert this subsection at the end of section 3, directly before the line `## 4. Deploy an image tag by hand` (the outer `~~~` fence is only for this plan; don't copy it):

~~~markdown
### Turn all production deploys off or on (#282)

The repository variable `PRODUCTION_DEPLOY` stops every production deploy in both modes: merges, runs of **deploy** by hand, **rollback**, and image builds. Only `true` deploys. Unset, empty, or any other value is off. CI checks still run on every pull request and merge.

Only the repository owner can change it: **Settings → Secrets and variables → Actions → Variables**, or:

```powershell
gh variable set PRODUCTION_DEPLOY --body false --repo konica/agent-tutor   # off: nothing deploys
gh variable set PRODUCTION_DEPLOY --body true --repo konica/agent-tutor    # on: today's rules
```

- **What a run shows.** Each **deploy** and **rollback** run has a `production-switch` job. With the switch off, a merge's run stays green and its summary says "Production deploys are OFF (PRODUCTION_DEPLOY is not true). Nothing was deployed." A run by hand or a rollback fails with the same message.
- **After turning it off,** cancel any deploy run that is still queued (`gh run list --workflow deploy.yml --limit 5`, then `gh run cancel <id>`). A queued deploy job passed its check when it was queued and may still start.
- **While it is off,** merged commits get no images, so a later rollback can't target them. A later deploy builds its own images.
- **To resume,** set it to `true`. The next merge deploys as usual. To deploy the current `main` now, run **deploy** by hand (section 4).
- **The per-mode variables** (`ON_PREMISE_AUTO_DEPLOY`, `NATIVE_CLOUD_AUTO_DEPLOY`) choose what deploys only while the switch is on. Tearing down one mode still uses its own variable (section 8).
- It is an operating control, not a security boundary: anyone with admin rights can flip it, and a merged change to the workflows can remove it.
~~~

In section 8, "Tear down the whole mode", step 1, replace
`1. **Stop deploys on merge** (section 3). Otherwise the next merge's image build deploys the deploy role and the registry again, or fails once the role is gone. Wait until no deploy run is in progress:`
with
`1. **Stop deploys on merge** (section 3). Otherwise the next merge's image build deploys the deploy role and the registry again, or fails once the role is gone. (`PRODUCTION_DEPLOY=false` stops it too, but also stops native-cloud.) Wait until no deploy run is in progress:`

- [ ] **Step 6: pilot runbook, README, architecture doc**

In `docs/runbooks/pilot-deploy.md` line 262, replace
`**What runs.** Native-cloud deploys when someone runs **deploy** by hand`
with
`**What runs.** While the production switch `PRODUCTION_DEPLOY` is `true` (`on-premise-deploy.md`, "Turn all production deploys off or on"), native-cloud deploys when someone runs **deploy** by hand`

In `README.md`, replace
`**On-premise (default).** Every merge to `main` (unless the repository variable `ON_PREMISE_AUTO_DEPLOY` is `false`)`
with
`**On-premise (default).** While the repository variable `PRODUCTION_DEPLOY` is `true`, every merge to `main` (unless `ON_PREMISE_AUTO_DEPLOY` is `false`)`
and add this paragraph after the "**Native-cloud (optional).**" paragraph:

```markdown
**Production switch.** The repository variable `PRODUCTION_DEPLOY` turns every production deploy on or off (merges, deploys by hand, rollbacks, image builds). Only `true` deploys: [`docs/runbooks/on-premise-deploy.md`](docs/runbooks/on-premise-deploy.md), "Turn all production deploys off or on".
```

In `docs/architecture/solution-architecture.md`, in the table row that starts `| 2. Merge to `main` |`, replace its last cell `If the checks fail, the deploy job never starts. |` with `If the checks fail, the deploy job never starts. Nothing deploys unless the repository variable `PRODUCTION_DEPLOY` is `true` (#282); with it off, a merge's run shows a notice and a run by hand fails. |`

- [ ] **Step 7: Verify**

Run: `cd infra && uv run pytest -q`
Expected: all pass (the whole infra suite, including `test_runbooks_name_the_current_workflows_and_environments`).

- [ ] **Step 8: Commit**

```bash
git add sdd/prd.md AGENTS.md sdd/adr/0012-on-premise-default-deployment-mode.md docs/runbooks/on-premise-deploy.md docs/runbooks/pilot-deploy.md README.md docs/architecture/solution-architecture.md infra/tests/test_workflows.py
git commit -m "Document the production deploy switch" -m "PRD v2.53, an ADR 0012 addendum, and the runbooks now say that nothing deploys unless PRODUCTION_DEPLOY is true (#282), how the owner flips it, what a run shows, and that queued runs need cancelling after switching off." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
