# Production deploy switch

| | |
|---|---|
| **Status** | Draft for PO review, 2026-10-12 |
| **Date** | 2026-10-12 |
| **Owner** | Thao Dinh (PO) |
| **Advisers** | Cloud architect and senior DevOps engineer (agent reviews, 2026-10-12) |
| **Applies to** | `.github/workflows/` (deploy, rollback, build-images, deploy-on-premise, deploy-native-cloud), `infra/tests/test_workflows.py`, `sdd/prd.md` §9.11–9.12, ADR 0012, deploy and teardown runbooks |

## 1. Problem

The repository became public on 2026-10-12. The product owner wants one setting that turns deployment to production on or off, without a code change.

Today three rules decide whether production changes (PRD §9.11, §9.12):

- On-premise deploys on every merge to `main` unless `ON_PREMISE_AUTO_DEPLOY` is `false`.
- Native-cloud deploys on a merge only while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`.
- A manual run of **deploy** (`workflow_dispatch`) and every **rollback** deploy whatever those variables say.

So there is no single place to stop all production changes. During an incident or a freeze, the owner has to remember two variables with opposite defaults, and still can't stop a manual run or a rollback.

## 2. Goal and success criteria

One repository variable stops every production deploy in both modes.

1. With the switch off, no job enters the `on-premise` or `native-cloud` environment: no merge deploy, no manual deploy, no rollback, no image build.
2. With the switch on, behavior is the same as today.
3. A missing, empty, or misspelled value means off.
4. Every run shows the switch's state, so nobody mistakes a skipped deploy for a deploy.
5. CI checks still run on every pull request and every merge.
6. A contract test fails if a workflow can reach a production environment without the switch.

**Decided with the PO:** a single master switch (not per-deploy approval, not a replacement for the per-mode variables). The repository owner (`konica`) flips it.

**Out of scope:**
- Approval of each deploy by the PO (GitHub environment required reviewers). It's free now that the repository is public and can be added later without changing this design.
- Any AWS-side control (§5.2).
- Hiding the account id in Actions logs (PR #276, separate).

## 3. The setting

| | |
|---|---|
| **Name** | `PRODUCTION_DEPLOY` |
| **Kind** | Repository variable (Settings → Secrets and variables → Actions → Variables). Not an environment variable: a job-level `if:` can read repository variables but not the variables of an environment it hasn't entered yet. |
| **On** | `true`. GitHub compares strings in expressions without regard to case, so `True` also counts; the shell check lowercases the value so both layers agree. |
| **Off** | Anything else, including unset. |
| **Who changes it** | The repository owner. On a personal-account repository only the owner can edit Actions variables. |
| **How** | Web UI as above, or `gh variable set PRODUCTION_DEPLOY --body true` / `--body false --repo konica/agent-tutor`. |

**Truth table**

| `PRODUCTION_DEPLOY` | Merge to `main` | Manual **deploy** run | **rollback** |
|---|---|---|---|
| not `true` | CI checks run. No images, no deploy. Run is green with a notice. | Run fails with an error. Nothing deployed. | Run fails with an error. Nothing deployed. |
| `true` | Today's rules: on-premise unless `ON_PREMISE_AUTO_DEPLOY=false`; native-cloud only if `NATIVE_CLOUD_AUTO_DEPLOY=true` | Deploys the chosen mode | Redeploys the chosen tag |

The per-mode variables keep their names and defaults. They only matter while the switch is on.

**Why fail closed:** the switch is a safety control on a public repository. A deleted variable, a typo, or a fresh fork or re-created repository should never deploy to production. The cost is one step at rollout (§6).

## 4. Design

### 4.1 Enforcement: the three workflows that hold production credentials

Only `build-images.yml`, `deploy-on-premise.yml`, and `deploy-native-cloud.yml` enter a production environment and name the deploy role. A test already enforces that (`test_only_main_and_rollback_reach_the_deploy_environments`). Each has one job. That job gets:

```yaml
    if: vars.PRODUCTION_DEPLOY == 'true'
```

One check point covers merges, manual runs, rollback, and any caller added later. The callers' existing conditions stay byte-for-byte the same, so behavior with the switch on is unchanged by construction. A job skipped here never starts, so it never checks out code or asks AWS for credentials.

**Image builds count as production deploys.** `build-images.yml` runs `cdk deploy` on the Registry and GitHubDeploy stacks before it pushes, and each push can expire a rollback target (ECR keeps the last 30 images). Turning the switch back on loses nothing: a deploy builds any missing images for its commit.

### 4.2 Visibility: a report job in each entry point

`deploy.yml` and `rollback.yml` get one job, `production-switch`, with no needs, no permissions beyond `contents: read`, and no AWS access:

```yaml
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

- **On a merge with the switch off:** the run stays green; the images and deploy jobs show as skipped; the notice and summary say nothing was deployed. A red run on every merge would teach people to ignore red.
- **On a manual run or rollback with the switch off:** the run fails, because a person asked for a deploy and a green run would look like success. `rollback.yml` is manual only, so its report job always fails when the switch is off.
- The report job doesn't gate anything; §4.1 does. If the two ever disagree, nothing deploys unless §4.1 allows it.

### 4.3 What stays the same

- `ci.yml` (the `checks` job) runs whatever the switch says.
- Environments `on-premise` and `native-cloud` still accept only `main`. The deploy roles still trust only those environments.
- Concurrency groups `deploy-on-premise` and `deploy-native-cloud` are unchanged.
- `evals-smoke.yml` and `openwiki-update.yml` use their own Bedrock-only roles and aren't production deploys; the switch doesn't affect them.

## 5. Decisions and alternatives

### 5.1 Mechanism

| Option | Verdict |
|---|---|
| Repository variable checked in the reusable workflows (chosen) | One enforcement point, covers every caller, readable in a job-level `if:`, owner flips it from the web UI. |
| Variable checked only in `deploy.yml` and `rollback.yml` | A future caller can forget it. Kept only as the report job (§4.2). |
| `gh workflow disable deploy.yml` | Also stops CI on merges, doesn't stop `rollback.yml`, and the state is easy to forget in the Actions list. |
| Environment setting (remove the `main` branch policy, environment variable) | Changed in a different place from the per-mode variables; a deploy job then fails late; an environment variable can't be read in a job-level `if:`. |

### 5.2 No AWS-side control

The deploy roles already trust only the GitHub environments (`github_deploy.py`, OIDC subject `…:environment:<env>`), so AWS defers to GitHub. An SSM parameter can't be checked at role assumption. A hand-made IAM deny or trust edit would drift, because `cdk deploy --all` and `build-images.yml` redeploy `GitHubDeploy`. Removing the OIDC provider would also break evals and OpenWiki, which share it (ADR 0016). None of that is worth it for a solo team.

### 5.3 What the switch is not

It's an operating control, not a security boundary. The runbook says so.

- **Fork pull requests:** already can't deploy. `deploy.yml` runs only on push to `main` or by hand, nothing uses `pull_request_target`, forks get no OIDC token or secrets, and the environments accept only `main`.
- **A stolen admin token:** can flip the switch. Defense: 2FA, fine-grained short-lived tokens.
- **A merged pull request that removes the `if:`:** with 0 required approvals and one maintainer, nothing stops it. The contract test catches accidents, not intent (the same PR can edit the test). The real control, if ever needed, is environment required reviewers with "prevent self-review".

## 6. Rollout and operation

1. **Before merging the implementation PR,** the owner runs `gh variable set PRODUCTION_DEPLOY --body true --repo konica/agent-tutor`. Otherwise that merge itself skips the on-premise deploy (safe, but surprising).
2. **To stop production changes:** set it to `false` (or delete it). Then cancel any deploy run already waiting in a concurrency group: a waiting job passed its `if:` when it was queued and may still start.
3. **While off,** merged commits get no images. A later rollback can't target them; a later deploy of a newer commit builds its own images.
4. **To resume:** set it to `true`. The next merge deploys as today. To deploy the current `main` at once, run **deploy** by hand.
5. **Teardown:** tearing down one mode still uses its per-mode variable (`ON_PREMISE_AUTO_DEPLOY=false`, `NATIVE_CLOUD_AUTO_DEPLOY` not `true`). The master switch stops both modes; it doesn't replace them.

## 7. Changes

**Workflows**
- `build-images.yml`, `deploy-on-premise.yml`, `deploy-native-cloud.yml`: job-level `if: vars.PRODUCTION_DEPLOY == 'true'`; header comment.
- `deploy.yml`, `rollback.yml`: the `production-switch` job; header comment with the truth table.

**Tests** (`infra/tests/test_workflows.py`)
- Every job in the three environment workflows has `if: vars.PRODUCTION_DEPLOY == 'true'`, and the comparison is `==` (fail closed, no `!=`).
- Every workflow that calls an environment workflow has a `production-switch` job, so a new caller without it fails.
- The existing `ON_PREMISE_IF` and `NATIVE_CLOUD_IF` strings are unchanged.
- The report script, run in bash: `true`/`True` → exit 0 and "ON"; empty or `false` on `push` → exit 0 with `::notice`; empty on `workflow_dispatch` → exit 1 with `::error`.
- `pilot-teardown.ps1`, `on-premise-deploy.md`, `pilot-deploy.md`, and PRD §9.12 mention `PRODUCTION_DEPLOY`.

**Scripts**
- `docs/runbooks/pilot-teardown.ps1` preflight: a merge redeploys native-cloud only if `PRODUCTION_DEPLOY` and `NATIVE_CLOUD_AUTO_DEPLOY` are both `true`. Stop only in that case; otherwise print why it's safe.

**Docs**
- `sdd/prd.md`: next version; "Changes from" row; §9.11 "Deployed" row; §9.12 Delivery gets the truth table.
- ADR 0012: a short addendum ("Production deploy switch").
- `docs/runbooks/on-premise-deploy.md`: intro, §3 "What runs" and a new "Turn all production deploys off or on" subsection (web UI path, `gh` commands, cancel queued runs, operating control not security boundary), §8 teardown note.
- `docs/runbooks/pilot-deploy.md` "What runs"; `docs/runbooks/pilot-teardown.md` preflight text.
- `README.md` and `docs/architecture/solution-architecture.md` where they describe deploy on merge.

## 8. Risks

| Risk | Mitigation |
|---|---|
| The owner forgets step 6.1 and the merge doesn't deploy | Run summary says why; PR description and runbook list the step; nothing breaks. |
| A queued deploy starts after the switch goes off | Runbook step 6.2: cancel queued runs. |
| A Dockerfile breaks while deploys are off and is found only at resume | Accepted. CI doesn't build images today either; a separate change could add `docker build` to CI. |
| Someone reads the switch as a security control | §5.3 in the runbook. |
