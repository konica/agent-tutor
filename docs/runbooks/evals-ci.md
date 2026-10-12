# CI smoke evals: the AWS role and the secrets (#226)

`.github/workflows/evals-smoke.yml` runs the smoke evals (`evals.run --split smoke`, PRD §10.3) in GitHub Actions. It runs on a pull request that changes the agent, and by hand from the Actions tab. The job builds the Compose app images, signs in to AWS with the role in `vars.EVALS_AWS_ROLE_ARN` (region us-east-1), starts the stack, loads the four seed PDFs of the eval learners, runs the smoke split as a LangSmith experiment, and writes the gate table and the experiment link to the job summary. It fails when a threshold in `backend/evals/thresholds.yaml` is breached.

A maintainer creates the role and the secrets once, by hand. Until they exist, the job skips with a message instead of failing.

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
gh secret set LANGSMITH_API_KEY --repo konica/agent-tutor   # paste a key for the smart-tutor-ci project's workspace
```

On Windows Git Bash, set `MSYS_NO_PATHCONV=1` first and use a folder that exists instead of `/tmp`.

## LangSmith

Runs trace to the project `smart-tutor-ci`, which LangSmith creates on the first trace. Local runs use `smart-tutor-local` and deployments use `smart-tutor-on-premise` and the like, so CI traces stay apart. The experiment link in the job summary opens the run's results.

## Pull requests from forks

GitHub issues no OIDC token and no secrets to workflows on fork PRs, so the job can't sign in. It skips with a notice. A missing secret (including Dependabot PRs, which don't get repository secrets) skips with a warning. A maintainer who wants the evals on a fork's change pushes the branch to this repository, or runs the workflow from the Actions tab on a branch.

Don't make `evals-smoke` a required status check: it is path-filtered, so PRs outside its paths would wait forever on "Expected".

After creating the role and the secret, start a first `workflow_dispatch` run from a branch to confirm LocalStack, the arXiv downloads, and Bedrock access.

## When a model changes

Change the model in `backend/src/smart_tutor/shared/config.py` and `infra/smart_tutor_infra/models.py`, then edit `evals-ci-bedrock-policy.json` to match. `infra/tests/test_evals_ci_access.py` fails until the JSON matches. Apply it with the same `sed` and `aws iam put-role-policy` lines as above.

## Cost

Each run ingests four seed PDFs and asks about ten questions: Bedrock and LangSmith usage only, a few cents. A newer commit on the same PR cancels the run in progress.
