# Pilot deploy (#56, #57, #58, #59, #139, #150)

**Optional mode.** On-premise is the default and deploys on every merge unless `ON_PREMISE_AUTO_DEPLOY` is `false` (`on-premise-deploy.md`). Native-cloud deploys only when chosen (#150).

Deploys the pilot's infrastructure and the `web`, `keycloak`, `api`, `agent`, `mcp-server`, and `worker` charts, so the CloudFront address serves the app shell, Keycloak at `/auth` on RDS, and the API at `/api`. The pilot now runs upload, processing, and chat: a learner uploads a PDF and asks a question about it (PRD §9.12, ADRs 0009 and 0010). It needs an account admin. Do [`pilot-aws-prerequisites.md`](pilot-aws-prerequisites.md) (#55) first. The big picture is in [`pilot-environment-overview.md`](pilot-environment-overview.md). Since #150 native-cloud deploys only when chosen (section 12); this runbook stays the manual path and the reference for what the workflow does.

To stop paying for the pilot, see [`pilot-teardown.md`](pilot-teardown.md) (#177).

Commands are for **PowerShell 7** (`pwsh`). Run them from the repository root with your admin profile.

## 1. Before you start

- #55 is done: CDK bootstrap, the `SmartTutor-prod-GitHubDeploy` stack, and the GitHub environment exist.
- Tools: Node 22+, uv, AWS CLI v2, kubectl, helm, Docker (see the table in the prerequisites file).
- Set up the shell so it talks to real AWS. A terminal that loaded `.env` sends calls to LocalStack, and access-key variables override the profile:

```powershell
Get-ChildItem Env: | Where-Object Name -like "AWS_ENDPOINT_URL*" | ForEach-Object { Remove-Item "Env:$($_.Name)" }
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
$env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = "true"
$env:AWS_PROFILE = "default"          # your admin profile
$env:AWS_REGION = "us-east-1"
$env:JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = "1"
aws sts get-caller-identity
```

- The profile must resolve to a principal listed in `smart-tutor:eks-admin-principals` in `infra/cdk.json` (pilot: `user/poweruser`, an IAM path in the deploy account). The cluster creator gets no admin access, so any other principal gets `Unauthorized` from kubectl and helm. Check the `Arn` that `aws sts get-caller-identity` prints.

## 2. Deploy the stacks (about 35 min; EKS is most of it, RDS adds about 10)

```powershell
Push-Location infra
uv sync
npx aws-cdk@latest diff -c smart-tutor:mode=native-cloud
npx aws-cdk@latest deploy --all --require-approval broadening -c smart-tutor:mode=native-cloud
Pop-Location
```

The pilot is native-cloud mode; without `-c smart-tutor:mode=native-cloud` the CDK app builds the on-premise stacks instead (#147), so every `cdk` command in this runbook passes it. `--all` orders the stacks by their dependencies (the Cluster stack waits for `SmartTutor-prod-GitHubDeploy`, which already exists). Read the outputs you need:

```powershell
function Get-Output($Stack, $Key) {
    aws cloudformation describe-stacks --stack-name "SmartTutor-prod-$Stack" --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
$VpcId = Get-Output Network VpcId
$Registry = Get-Output Registry RegistryUri
$Url = Get-Output Edge CloudFrontUrl
$Bucket = Get-Output Storage DocumentsBucketName
$Queue = Get-Output Storage IngestQueueUrl
$VpcId; $Registry; $Url; $Bucket; $Queue
```

## 3. Connect kubectl

```powershell
aws eks update-kubeconfig --name smart-tutor-prod --region us-east-1
kubectl get nodes        # 2 nodes, both Ready
```

Your admin principal and the deploy role have cluster-admin access entries; no other principal does. If kubectl says `Unauthorized`, run `aws sts get-caller-identity` and compare the `Arn` with `smart-tutor:eks-admin-principals` in `infra/cdk.json`.

## 4. Install the add-ons

Versions are pinned. The values files are in `deploy/helm/addons/`.

```powershell
helm repo add eks https://aws.github.io/eks-charts
helm repo add external-secrets https://charts.external-secrets.io
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f deploy/helm/addons/aws-load-balancer-controller.yaml --set vpcId=$VpcId --wait
helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets --create-namespace -f deploy/helm/addons/external-secrets.yaml --wait
helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 -n kube-system -f deploy/helm/addons/metrics-server.yaml --wait
```

## 5. Build and push the images

The nodes are x86_64, so build `linux/amd64`. On Apple silicon add `--platform linux/amd64`. These push to native-cloud's own repositories `smart-tutor/<service>` (`SmartTutor-prod-Registry`); on-premise has its own since #206.

```powershell
$Tag = git rev-parse --short=12 HEAD
aws ecr get-login-password | docker login --username AWS --password-stdin $Registry
docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$Registry/smart-tutor/web:$Tag" web
docker push "$Registry/smart-tutor/web:$Tag"
docker build -t "$Registry/smart-tutor/keycloak:$Tag" deploy/keycloak
docker push "$Registry/smart-tutor/keycloak:$Tag"
docker build --target api -t "$Registry/smart-tutor/api:$Tag" backend
docker push "$Registry/smart-tutor/api:$Tag"
foreach ($t in "agent", "mcp", "worker") {
    docker build --target $t -t "$Registry/smart-tutor/${t}:$Tag" backend
    docker push "$Registry/smart-tutor/${t}:$Tag"
}
```

`/api` and `/auth` are relative, so the web image does not depend on the CloudFront address. The Keycloak image is optimized once at build time (ADR 0010).

## 6. Install the app

```powershell
helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace -f deploy/helm/smart-tutor/values-prod.yaml --set global.imageRegistry=$Registry --set global.imageTag=$Tag --set global.publicUrl=$Url --set global.documentsBucket=$Bucket --set global.ingestQueueUrl=$Queue --set-string global.langsmith.samplingRate=1 --wait=legacy --timeout 15m
```

`global.publicUrl` is the CloudFront address from step 2. Without it Keycloak refuses to start. `global.documentsBucket` and `global.ingestQueueUrl` are the Storage outputs from step 2; the production chart (it applies when `global.secretStore` is set) refuses to render without them. The first install runs the `db-bootstrap` hook, which creates the database roles and databases. Keycloak's first start takes about 2 min (schema and realm import), so the wait is slow the first time; `--timeout 15m` (Helm's default is 5 min) covers the hook plus that first start. Use `--wait=legacy`: with Helm 4's default (`--wait`, the watcher strategy) Helm sits out the whole timeout on every hook that isn't a Job (the SecretStore, the ExternalSecrets, the ConfigMap), about an hour for a first install. Before the API rolls out, the `migrate` hook brings the app database to the latest Alembic revision; if it fails, the release fails and the running API stays. A failed hook Job stays for debugging: `kubectl -n smart-tutor logs job/migrate`.

Before the first install, or the first deploy after #229 on an existing release (the agent and worker pods stay in `CreateContainerConfigError` until `helm --wait` times out), create the LangSmith API key's secret (`aws secretsmanager create-secret --name smart-tutor/langsmith/api-key --secret-string <service key>`); without it the agent and worker pods can't start. Traces go to the LangSmith project `smart-tutor-native-cloud` (ingestion: `smart-tutor-native-cloud-ingestion`). Set both projects' retention in LangSmith (Projects, the project, Retention) to **Extended (180 days)**: LangSmith SaaS keeps no trace longer than 180 days, which meets D25 (details: `on-premise-deploy.md` section 10).

## 7. Check

A new distribution and new targets can take a few minutes to settle. A 502 or 503 at first is expected: retry after 2 to 3 minutes. If the API pods CrashLoop, run `kubectl -n smart-tutor logs deploy/api`; a `ParameterNotFound` error means the Config stack is not deployed (run step 2).

```powershell
kubectl -n smart-tutor get pods,externalsecrets,targetgroupbindings
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-web --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-keycloak --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-api --query "TargetGroups[0].TargetGroupArn" --output text)
curl.exe -sI $Url
curl.exe -sI ($Url -replace '^https','http')
$d = curl.exe -s "$Url/auth/realms/smart-tutor/.well-known/openid-configuration" | ConvertFrom-Json; $d.issuer; $d.token_endpoint; $d.jwks_uri
aws rds describe-db-instances --db-instance-identifier smart-tutor-prod --query "DBInstances[0].PubliclyAccessible"
```

- The pods are `Running`, the ExternalSecrets show `SecretSynced`, and the `TargetGroupBinding` objects exist.
- Target health shows 2 healthy web targets and healthy Keycloak targets, and 2 healthy API targets.
- The HTTPS request returns 200; the HTTP request returns 301 to HTTPS.
- The OpenID configuration shows `issuer` `<Url>/auth/realms/smart-tutor`, with your CloudFront address as `<Url>`, and `token_endpoint` and `jwks_uri` also start with `$Url/auth/`. An internal ALB name there means CloudFront is not forwarding the viewer Host (ADR 0010).
- The database is private: the RDS query prints `False`.
- The `agent`, `mcp-server`, and `worker` pods are `Running` (`agent` has 2 replicas, the others 1).
- The agent and the MCP server answer inside the cluster. The deploy workflow runs the same check from `deploy/api`: `http://agent/healthz` must return 200, and `http://mcp-server/mcp` must return 401 (no token):

```powershell
kubectl -n smart-tutor exec deploy/api -- python -c "import urllib.request as u; print(u.urlopen('http://agent/healthz', timeout=10).status)"
@'
import urllib.error as e, urllib.request as u
try:
    u.urlopen('http://mcp-server/mcp', timeout=10)
except e.HTTPError as x:
    print(x.code)
'@ | kubectl -n smart-tutor exec -i deploy/api -- python -
kubectl -n smart-tutor logs deploy/worker --tail 20      # polling the queue, no errors
```

- Open `$Url` in a browser: the app shell loads.
- The API answers through CloudFront:

```powershell
curl.exe -si "$Url/api/me"          # 401, WWW-Authenticate: Bearer
curl.exe -s "$Url/api/healthz"      # {"status":"ok"}
```

- The ALB is not public:

```powershell
aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].Scheme" --output text   # internal
$Alb = aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].DNSName" --output text
Resolve-DnsName $Alb                                                                                       # only 10.40.x.x addresses
```

- Check the budget in **Billing → Budgets → smart-tutor-prod-monthly** (the amount in `smart-tutor:budget-monthly-usd`, emails at 80% actual and 100% forecasted). Delete the old $20 budget if it is still there (#55 follow-up).

## 8. Manage client accounts

Keycloak has no self-registration yet (#47), so you create each client's account.

1. Get the admin password. Do not paste it anywhere:

```powershell
aws secretsmanager get-secret-value --secret-id smart-tutor/keycloak/admin --query SecretString --output text
```

2. Sign in at `$Url/auth/admin` as `admin`. Keycloak shows a banner for the temporary admin. Optionally create a permanent admin user in realm **master** with the role `admin`, sign in as that user, and delete the bootstrap one.
3. Create the account: realm **smart-tutor** → **Users → Add user** → email, first and last name, **Email verified** on → **Create** → **Credentials → Set password** with **Temporary** on. Use at least 12 characters, and not the email address.
4. Demo (#57): open `$Url/auth/realms/smart-tutor/account` in a private window and sign in as the new user. Keycloak asks for a new password, then shows the account console. In DevTools → Application → Cookies for the CloudFront address, `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` show **Secure**: this proves CloudFront's `Forwarded: proto=https` reaches Keycloak (ADR 0010).
5. To remove access: **Users →** the user → **Enabled** off. Sessions end. The PRD has no account deletion.

Send the client the address, username, and temporary password through separate channels, after the demo below passes.

### Demo: a learner signs in (#58)

Use the account from step 8. Never paste a token anywhere except the variable below.

1. Open `$Url` in a private window and choose **Sign in**. Sign in as the step 8 account. The Library shows, with the user's name in the user menu.
2. In DevTools → Network, find the request to `/api/me` and copy the `Authorization` value after `Bearer `. Keep it in `$Tok`: step 3 reuses it after you sign out. In PowerShell:

```powershell
$Tok = "<paste>"
curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer $Tok" "$Url/api/me"      # 200
```

3. Sign out in the app and run the same `curl.exe` again with the `$Tok` captured in step 2: `401`.
4. Call without a token: `401` with `WWW-Authenticate: Bearer`.

```powershell
curl.exe -si "$Url/api/me"
```

5. Take Keycloak down. A rolling restart never does (`maxUnavailable: 0`), so scale it to zero. First sign in again in the app and copy a fresh token into `$Tok2` the same way as in step 2 (the old `$Tok` was revoked by the sign-out). Do not paste it anywhere else.

```powershell
$Tok2 = "<paste>"
kubectl -n smart-tutor scale deploy/keycloak --replicas=0
kubectl -n smart-tutor get pods -l app.kubernetes.io/name=keycloak      # repeat until no pod is Running
curl.exe -s -o NUL -w "%{http_code}" "$Url/api/healthz"                                          # 200
curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer $Tok2" "$Url/api/me"              # 401, never 5xx
kubectl -n smart-tutor scale deploy/keycloak --replicas=1
kubectl -n smart-tutor rollout status deploy/keycloak
curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer $Tok2" "$Url/api/me"              # 200 again
```

   Keycloak keeps its sessions in the database, so the same `$Tok2` works again, and a new sign-in in the app works. The next `helm upgrade` restores the replica count from the values in any case.

6. DevTools shows no `OPTIONS` preflight to `/api`, because the app and the API share one origin.

### Demo: upload and ask (#139)

Use two learner accounts from step 8 (learner A and learner B), and a PDF from the seed corpus. Use private windows so the sessions stay apart.

1. As learner A, upload the PDF in the Library. It shows *processing*, then reaches *ready* with a title and subjects (choose subjects if asked). The upload goes from the browser straight to the bucket, so a failure here that mentions CORS is a bucket setting (see Troubleshooting).
2. Ask a question about the document. The answer streams in and cites the document; the conversation lists it under the documents used. The answer shows citations with the document, page, and passage. (Opening the PDF at the passage comes with the PDF viewer, US-4b, which is not built yet.)
3. As learner B, the document is not in the Library. Ask a question about the same topic: the answer does not cite it.
4. Retry (#95): make a document fail (for example, upload a PDF with more than 500 pages, or one that is not a real PDF renamed to `.pdf`), then choose **Retry** on the failed document. It returns to *processing*.

Record the statuses and screenshots on the PR. Do not include tokens.

### Troubleshooting uploads (#139)

- **An upload stays in *processing*.** Read the worker logs: `kubectl -n smart-tutor logs deploy/worker --tail 100`. A message is retried until it has been received 5 times, then it goes to the dead-letter queue. Check its depth (the DLQ is the ingest queue's name plus `-dlq`):

```powershell
$Dlq = $Queue -replace 'smart-tutor-ingest$', 'smart-tutor-ingest-dlq'
aws sqs get-queue-attributes --queue-url $Dlq --attribute-names ApproximateNumberOfMessages
```

- **A CORS error on upload.** The browser posts straight to the bucket, so the bucket's CORS must name the CloudFront address: `aws s3api get-bucket-cors --bucket $Bucket`. The allowed origin must equal `$Url`.
- **Bedrock `AccessDeniedException`** in the worker or agent logs. Check the role policy first: this error usually means a wrong model ARN or region in the Pod Identity role, or a service control policy (SCP) that blocks the call. The two models are the chat model `us.amazon.nova-2-lite-v1:0` (an inference profile that routes to `amazon.nova-2-lite-v1:0` in us-east-1, us-east-2, and us-west-2) and the embedding model `amazon.nova-2-multimodal-embeddings-v1:0`. As a last step, check that model access is on for both in the Bedrock console, in us-east-1.
- **Replacing the CloudFront distribution.** The Storage stack imports Edge's CloudFront URL export for its CORS rule. If the distribution is ever replaced, deploy in two steps, because CloudFormation can't change an export that another stack imports.

## 9. Update after a change

The native-cloud deploy workflow does all of this (section 12). By hand: deploy infrastructure changes with CDK first (`npx aws-cdk@latest deploy --all` from `infra/`), then rebuild and push the images with a new tag and run the `helm upgrade` from step 6 again (with `--timeout 15m`). The order matters: the API pods read their SSM parameters at startup through a Pod Identity association that the CDK stacks create. The upgrade runs the `db-bootstrap` and `migrate` hooks first. Only `db-bootstrap` resets database passwords, so a password rotated in Secrets Manager reaches the database there; `migrate` only applies the schema. Since #139, five deployments read a database secret: `keycloak` (`keycloak-db`, database `keycloak`) and `api`, `agent`, `mcp-server`, `worker` (`api-db`, `agent-db`, `mcp-db`, `worker-db`, all copies of `smart-tutor/db/app`). Running pods keep the old password (the environment is read at start, and External Secrets refreshes these secrets only hourly), so after rotating, run the `helm upgrade`, then force the syncs and restart all five:

```powershell
foreach ($Secret in "keycloak-db", "api-db", "agent-db", "mcp-db", "worker-db") {
    kubectl -n smart-tutor annotate externalsecret $Secret force-sync=$(Get-Date -UFormat %s) --overwrite
}
foreach ($Deploy in "keycloak", "api", "agent", "mcp-server", "worker") {
    kubectl -n smart-tutor rollout restart deploy/$Deploy
}
```

The agent receives the app database secret but doesn't use it yet, so restarting it is harmless and keeps its copy current. To rotate the LangSmith API key (`smart-tutor/langsmith/api-key`) or the learner-hash key, do the same with the ExternalSecrets `agent-langsmith` and `worker-langsmith` and the deployments `agent` and `worker`. Merging redeploys (it runs the hooks and the CDK deploy), but after a rotation the force-sync and `rollout restart` commands are still manual.

## 10. Tear down

Use the script in [`pilot-teardown.md`](pilot-teardown.md) (#177). It uninstalls the release and add-ons, destroys the stacks one at a time with `--exclusively`, because a plain destroy of `Network` would also delete its dependents, the `Registry` among them. It deletes the `Registry` too. It keeps the final RDS snapshot and the documents bucket unless you pass a switch.

## 11. Costs

About **$250–300 a month** while idle, including RDS (`db.t3.micro` with 20 GiB, about $15 a month). During the testing phase the budget is **$20 a month** (`smart-tutor:budget-monthly-usd` in `infra/cdk.json`), with alerts. That is below the idle cost, so expect the 80% alert email within the first days the environment runs. Raise the value and run `npx aws-cdk@latest deploy SmartTutor-prod-Budgets -c smart-tutor:mode=native-cloud` from `infra/` when the pilot starts.

## 12. Native-cloud is optional: deploy and roll back (#59, #150)

**What runs.** While the production switch `PRODUCTION_DEPLOY` is `true` (`on-premise-deploy.md`, "Turn all production deploys off or on"), native-cloud deploys when someone runs **deploy** by hand (Actions, **deploy**, *Run workflow*) with mode `native-cloud`, or on every push to `main` while the repository variable `NATIVE_CLOUD_AUTO_DEPLOY` is `true` (unset is off). `.github/workflows/deploy.yml` runs the CI checks (`ci.yml`), then `build-images.yml`, which builds the six images (`web`, `keycloak`, `api`, `agent`, `mcp`, `worker`) tagged with the full commit SHA (skipped when they already exist). Then `deploy-native-cloud.yml` runs in the GitHub environment `native-cloud`: `cdk deploy --all`, the add-ons, `helm upgrade --install smart-tutor` with the Storage outputs, the in-cluster check (the agent answers `/healthz`, the MCP server refuses a call without a token), and `deploy/pilot/smoke_test.py` against the CloudFront address. One native-cloud deployment runs at a time (concurrency group `deploy-native-cloud`); a second one waits. To turn on deploy on merge: `gh variable set NATIVE_CLOUD_AUTO_DEPLOY --body true --repo konica/agent-tutor`. Each mode has its own images job in its own environment (`images-native-cloud` runs in `native-cloud`), so native-cloud needs no on-premise setup.

**Concurrency.** GitHub keeps only one *pending* run per group. If several merges land while a deploy runs, only the newest waits and the ones in between are cancelled (latest wins). A queued rollback can likewise be replaced by a newer merge's deploy.

**Watch it.** `gh run list --workflow deploy.yml --limit 5`, then `gh run watch`. The run summary names the deployed SHA and address. A red step is the failure; the release stays as Helm left it (`helm -n smart-tutor history smart-tutor`).

**Optional approval.** **Settings → Environments → native-cloud → Required reviewers** makes each deploy wait for an approval.

**Image build overlapping a deploy.** The image build's CDK step (the registry and deploy-role stacks) runs outside the `deploy-native-cloud` queue, so a build that overlaps a running native-cloud deploy can fail. Re-run the workflow once the deploy has finished.

**Smoke test by hand.**

```powershell
python deploy/pilot/smoke_test.py $Url
```

**A stuck release.** If a run is cancelled or times out during `helm upgrade --wait`, the release can stay in `pending-upgrade`, and the next deploy fails with "another operation (install/upgrade/rollback) is in progress". From a laptop (step 3 sets up kubectl and helm access), find the last deployed revision, roll back to it, then re-run the deploy (`gh run rerun <id>`, or merge again):

```powershell
helm -n smart-tutor history smart-tutor
helm -n smart-tutor rollback smart-tutor <last deployed revision>
```

If the only revision is a `pending-install` (the first install never finished), there is nothing to roll back to: uninstall it instead, then re-run the deploy. Nothing is lost, because the databases live in RDS and the hooks recreate what they need:

```powershell
helm -n smart-tutor uninstall smart-tutor
```

**Roll back.**

```powershell
gh workflow run rollback.yml --ref main -f mode=native-cloud -f image_tag=<full SHA of an earlier successful deploy>
```

Find the SHA with `gh run list --workflow deploy.yml --status success --limit 10 --json headSha,displayTitle,createdAt`. The workflow checks the images are still in ECR (the last 30 per repository), checks out that commit's chart, and runs the add-ons, `helm upgrade`, and the smoke test, without CDK or a build. It doesn't undo infrastructure changes. It checks native-cloud's repositories only: a commit has images there only if it was deployed to native-cloud (each mode builds into its own repositories since #206; commits merged before #206 were built into `smart-tutor/*` for both modes, so those within the last 30 images are there).

- The native-cloud deploy reads the SSM parameter `/smart-tutor/trace-sampling-rate` with the deploy role, whose `ssm:GetParameter` permission arrives when GitHubDeploy is redeployed (`build-images.yml` does that for a new commit's first native-cloud build). A rollback run before any post-#229 native-cloud build fails at "Read the stack outputs" with AccessDenied: deploy the `SmartTutor-prod-GitHubDeploy` stack (or run deploy with infrastructure) first.
- It runs the old commit's chart, add-on values, and smoke test. Commits from before deploy on merge (no `deploy/pilot/smoke_test.py`, images not tagged with the full SHA) can't be rolled back to with the workflow; use the laptop path.
- The workflow also can't roll back to a commit from before #139. Those commits never pushed the `smart-tutor/agent`, `mcp`, or `worker` images, and their chart has no agent or MCP server for the in-cluster check. To go back that far, use `helm -n smart-tutor rollback smart-tutor <revision>`; find the revision with `helm -n smart-tutor history smart-tutor`.
- Rollback across a migration doesn't work: the old image's `migrate` hook can't find the newer Alembic revision in the database, so the release stops before anything rolls out. Fix forward instead (revert the PR and merge).

**By hand (laptop) instead:** steps 3 and 6 with `$Tag` set to the tag the images were pushed with: the full SHA for workflow deploys, the 12-character short SHA for manual step 5 builds.
