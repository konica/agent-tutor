# CI smoke evals: the AWS role, the Langfuse keys, and the night rule (#226, #320)

`.github/workflows/evals-smoke.yml` runs the smoke evals (`evals.run --split smoke`, PRD §10.3) in GitHub Actions. It runs on a pull request that changes the agent, and by hand from the Actions tab. The job checks that Langfuse answers, builds the Compose app images, signs in to AWS with the role in the secret `EVALS_AWS_ROLE_ARN` (region us-east-1), starts the stack, loads the four seed PDFs of the eval learners, runs the smoke split as Langfuse experiments in the `smart-tutor-evals` project, and writes the gate table and the experiment links to the job summary. It fails when a threshold in `backend/evals/thresholds.yaml` is breached.

A maintainer creates the role, the secrets, and the variable once, by hand. Until they exist, the job skips with a message instead of failing.

| Name | Kind | What |
|---|---|---|
| `EVALS_AWS_ROLE_ARN` | secret | The Bedrock-only role below |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | secrets | A key pair of the Langfuse project `smart-tutor-evals` (organization Smart Tutor), made for CI |
| `LANGFUSE_BASE_URL` | repository variable | The Langfuse host's URL, `https://sec-dog.duckdns.org` (ADR 0023 §5) |

## Why a separate role

The evals call Bedrock and nothing else in AWS. The role `smart-tutor-evals-ci` may only invoke the models the evals call (the agent model and its inference profile, the embedding model, and the judge model). It has no deploy rights, no S3, no SSM. The deploy roles in `GitHubDeploy` trust only their environments (`main` deploys); this one trusts this repository's pull requests and branch runs, so it must not be able to change anything. That trust (`pull_request` and `ref:refs/heads/*`) lets any workflow on any branch, written by anyone with push access, use the role. That is deliberate and bounded by the invoke-only permissions; the cost is Bedrock spend.

`infra/tests/test_evals_ci_access.py` keeps the two JSON files in this folder in step with `infra/smart_tutor_infra/models.py` and the OIDC subject prefix in `infra/cdk.json`.

## Create it

Run once, with your admin profile and real AWS (see `on-premise-deploy.md` §1 for the shell setup). It assumes the account's GitHub OIDC provider exists; native-cloud's `GitHubDeploy` stack creates it (ADR 0016). If `aws iam list-open-id-connect-providers` shows no `token.actions.githubusercontent.com`, create it first:

```bash
aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com --client-id-list sts.amazonaws.com
```

Then, from the repository root:

```bash
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" docs/runbooks/evals-ci-trust-policy.json > /tmp/trust.json
sed "s/ACCOUNT_ID/$ACCOUNT_ID/g" docs/runbooks/evals-ci-bedrock-policy.json > /tmp/bedrock.json
aws iam create-role --role-name smart-tutor-evals-ci --max-session-duration 3600 \
  --assume-role-policy-document file:///tmp/trust.json --description "GitHub Actions smoke evals: Bedrock invoke only (#226)"
aws iam put-role-policy --role-name smart-tutor-evals-ci --policy-name bedrock-invoke --policy-document file:///tmp/bedrock.json
gh secret set EVALS_AWS_ROLE_ARN --repo konica/agent-tutor --body "arn:aws:iam::$ACCOUNT_ID:role/smart-tutor-evals-ci"
```

On Windows Git Bash, set `MSYS_NO_PATHCONV=1` first and use a folder that exists instead of `/tmp`.

## Langfuse

The CI's runs go to the same project as developers' runs, `smart-tutor-evals`, because the experiments must run on the dataset versions developers publish there (ADR 0023 §5). In Langfuse, create a key pair for CI: Smart Tutor → `smart-tutor-evals` → Settings → API Keys → Create, with the note "GitHub Actions evals-smoke". It is separate from developers' pairs, so it can be revoked alone. Then, from the repository root:

```bash
gh secret set LANGFUSE_PUBLIC_KEY --repo konica/agent-tutor     # paste pk-lf-...
gh secret set LANGFUSE_SECRET_KEY --repo konica/agent-tutor     # paste sk-lf-...
gh variable set LANGFUSE_BASE_URL --repo konica/agent-tutor --body https://sec-dog.duckdns.org
```

Each smoke run is a run of each dataset version's Langfuse dataset (`smart-tutor-ask/smoke-v3` → Runs), named `ci <start time>Z`, with `environment: ci` in its metadata; a developer's runs are named `local …`. The links in the job summary open the runs. Each example is a trace with its scores; the SDK files those traces under the environment `sdk-experiment`, so tell CI's runs from developers' by run name or metadata.

The smoke split runs on the newest published versions unless a dataset file pins one (`backend/evals/README.md`, "Datasets"). A split that was never published to Langfuse is "not run", and a run where nothing ran fails: publish with `make evals-publish` first.

## At night

The Langfuse host runs 07:00–18:00 Asia/Ho_Chi_Minh (ADR 0022). The job's first step after the access check calls `<LANGFUSE_BASE_URL>/api/public/health`, three times over about 45 seconds. If Langfuse doesn't answer, the job **fails** before building anything or calling Bedrock, with "Langfuse is off 18:00–07:00 Asia/Ho_Chi_Minh: re-run this job after 07:00, or start the host (`docs/runbooks/langfuse-host.md`)" (ADR 0023 §4). It fails rather than skips, so an agent change merged at night can't pass the gate unseen. Re-run the job from the PR's Checks tab after 07:00, or start the host by hand as `langfuse-host.md` says and re-run it. CI never starts the host itself.

If the host goes off while a run is in progress (a run started just before 18:00), the SDK logs each trace or score it can't send, and the job fails with "Can't reach Langfuse" when it next reads a dataset. Re-run it in the morning.

## Pull requests from forks

GitHub issues no OIDC token and no secrets to workflows on fork PRs, so the job can't sign in. It skips with a notice. A missing secret (including Dependabot PRs, which don't get repository secrets) skips with a warning. A maintainer who wants the evals on a fork's change pushes the branch to this repository, or runs the workflow from the Actions tab on a branch.

Don't make `evals-smoke` a required status check: it is path-filtered, so PRs outside its paths would wait forever on "Expected".

After creating the role, the secrets, and the variable, start a first `workflow_dispatch` run from a branch between 07:00 and 18:00 to confirm Langfuse, LocalStack, the arXiv downloads, and Bedrock access.

## When a model changes

Change the model in `backend/src/smart_tutor/shared/config.py` and `infra/smart_tutor_infra/models.py`, then edit `evals-ci-bedrock-policy.json` to match. `infra/tests/test_evals_ci_access.py` fails until the JSON matches. Apply it with the same `sed` and `aws iam put-role-policy` lines as above.

## Cost

Each run ingests four seed PDFs and asks the smoke split's questions (at most 30 per dataset): Bedrock usage only, a few cents. Langfuse is self-hosted and costs nothing per run. A newer commit on the same PR cancels the run in progress.
