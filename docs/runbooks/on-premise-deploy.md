# On-premise deploy (#148, #149, #153, #154)

Deploys on-premise mode (ADR 0012, PRD §9.12): one EC2 VM runs Smart Tutor with Docker Compose, and Caddy serves it over HTTPS at `https://smart-tutor.duckdns.org` (a DuckDNS name pointed at the Elastic IP, section 8) with a Let's Encrypt certificate. This runbook covers the first deploy and a manual redeploy. It brings up Postgres, Keycloak, the API, the web app, Caddy, the agent, the MCP server, and the worker, so a learner can sign in, upload a PDF, and ask about it (#149). Deploy on merge is #150. Backups and restore: `on-premise-backups.md` (#151). Alarms and weekly patching: `on-premise-monitoring.md` (#152); after the first deploy, every alert recipient confirms the subscription email.

Commands are for **PowerShell 7** (`pwsh`). Run them from the repository root with your admin profile. No command here prints a secret. Don't paste the values you read in step 4 anywhere.

## What runs where

| Piece | Where |
|---|---|
| CDK stacks `SmartTutor-OnPremise-prod-*` | `infra/` with `-c smart-tutor:mode=on-premise` (the default mode): Storage, Config, Budgets, GitHubDeploy, and **Host** (`infra/smart_tutor_infra/stacks/host.py`) |
| Images | ECR `smart-tutor/<service>:<commit SHA>`, shared with native-cloud (its Registry stack owns the repositories) |
| Files on the VM | `deploy/` is uploaded as a CDK asset; the deploy unpacks it to `/opt/smart-tutor` and runs `/opt/smart-tutor/on-premise/deploy.sh` |
| Settings and secrets | SSM `/smart-tutor-on-premise/*` and Secrets Manager `smart-tutor-on-premise/*`. On the VM, `deploy.sh` renders them into `/etc/smart-tutor/smart-tutor.env` (root only, mode 600) |
| AWS from the containers | The agent, MCP server, worker, and API use the instance profile (IMDSv2, hop limit 2): Bedrock, the on-premise bucket and ingest queue, and SSM `/smart-tutor-on-premise/*`. One role holds what native-cloud gives each service separately. The worker reaches them only through `egress-proxy` (an allowlist; ADR 0014) |
| Data | The data volume, mounted at `/data`: Postgres in `/data/postgres` (the app and Keycloak databases), and Caddy's certificates in `/data/caddy` |
| Public name | `smart-tutor.duckdns.org` on DuckDNS, in the account of the Google account `dtrungthao@gmail.com`. Its token is the secret `smart-tutor-on-premise/duckdns/token`, created by hand, not by CDK (section 8) |

The Host stack creates a VPC with one public subnet, no NAT, and an S3 gateway endpoint. It also creates a `t3.large` Amazon Linux 2023 instance with no SSH key and a security group that admits TCP 80 and 443 only, plus an Elastic IP and a 50 GB encrypted gp3 data volume. The SSM document `smart-tutor-on-premise-deploy` runs the deploy. The instance size is the context `smart-tutor:on-premise-instance-type` in `infra/cdk.json`. The domain is `smart-tutor:on-premise-domain`: `smart-tutor.duckdns.org`, and empty means `<Elastic IP>.sslip.io`.

## 1. Before you start

- CDK is bootstrapped in the account (`pilot-aws-prerequisites.md` §2), and the GitHub OIDC provider exists (native-cloud's `SmartTutor-prod-GitHubDeploy` created it; the on-premise deploy role reuses it).
- The ECR repositories exist (`SmartTutor-prod-Registry`) and hold images for the commit you want. Every merge to `main` pushes them, tagged with the full commit SHA. On-premise needs `api`, `web`, `keycloak`, `agent`, `mcp`, and `worker`.
- The DuckDNS token is stored (section 8). Without it a deploy still works but can't point the name at a new Elastic IP.
- Tools: Node 22+, uv, AWS CLI v2, and the [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) to open a shell on the VM.
- Set up the shell for real AWS (the same as `pilot-deploy.md` §1):

```powershell
Get-ChildItem Env: | Where-Object Name -like "AWS_ENDPOINT_URL*" | ForEach-Object { Remove-Item "Env:$($_.Name)" }
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
$env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = "true"
$env:AWS_PROFILE = "default"          # your admin profile
$env:AWS_REGION = "us-east-1"
$env:JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = "1"
aws sts get-caller-identity
```

## 2. Deploy the stacks (about 10 min)

```powershell
Push-Location infra
uv sync
npx aws-cdk@latest diff -c smart-tutor:mode=on-premise
npx aws-cdk@latest deploy --all --require-approval broadening -c smart-tutor:mode=on-premise
Pop-Location

function Get-Output($Key) {
    aws cloudformation describe-stacks --stack-name SmartTutor-OnPremise-prod-Host `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
$InstanceId = Get-Output InstanceId
$Url = Get-Output PublicUrl
$InstanceId; $Url
```

`-c smart-tutor:mode=on-premise` is the default, but writing it out avoids deploying the wrong mode. The outputs hold no secret. At first boot the instance attaches and formats the data volume, then installs Docker and the Compose plugin (its digest is checked). Wait until SSM lists the instance as `Online`, usually 2 to 3 minutes:

```powershell
aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$InstanceId" --query "InstanceInformationList[0].PingStatus" --output text
```

## 3. Deploy an image tag

Pick the commit whose images to run. It must be a full 40-character SHA with images in ECR:

```powershell
$Tag = git rev-parse origin/main
foreach ($Repo in "api", "web", "keycloak", "agent", "mcp", "worker") {
    aws ecr describe-images --repository-name "smart-tutor/$Repo" --image-ids imageTag=$Tag --query "imageDetails[0].imageTags[0]" --output text
}
```

Run the deploy through SSM Run Command and wait for it. The first deploy takes about 5 minutes: Keycloak creates its schema and imports the realm, and Caddy gets its certificate.

```powershell
$CommandId = aws ssm send-command --document-name smart-tutor-on-premise-deploy --instance-ids $InstanceId `
    --parameters "ImageTag=$Tag" --comment "Deploy $Tag" --query Command.CommandId --output text
aws ssm wait command-executed --command-id $CommandId --instance-id $InstanceId
aws ssm get-command-invocation --command-id $CommandId --instance-id $InstanceId `
    --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

`aws ssm wait` gives up after about 100 seconds. If it does, run it again; the command keeps running on the VM, with a 30-minute limit. `deploy.sh` does the following:

1. It waits for `/data`, then renders settings from SSM and secrets from Secrets Manager into `/etc/smart-tutor/smart-tutor.env`.
2. It pulls the images, starts Postgres, and creates or updates the `smart_tutor` and `keycloak` roles and databases (`deploy/helm/smart-tutor/files/db-bootstrap.sql`, the same script as native-cloud).
3. It runs the migrations, then `docker compose up -d --wait`, which waits until every service is healthy. A deploy fails if any service doesn't become healthy within 15 minutes.
4. It checks the worker's isolation (user 10001, read-only root filesystem, all capabilities dropped, no new privileges) and fails the deploy otherwise, and proves the worker's egress block from inside it (`check-egress.py`): a direct connection or a proxied one to another host must fail, and S3, SQS, SSM, Bedrock, and Postgres must answer. It also checks from the API container that the agent answers `/healthz` and the MCP server refuses a call without a token.
5. It creates the test learner if it is missing.

The first deploy of #153 recreates Postgres once (it joins the worker network); the API, Keycloak, and worker reconnect within seconds.

The output lists each service's status and ends with `Deployed <tag> to https://...`. It never contains a secret.

## 4. Check

1. **Certificate and routes.** Open `$Url` in a browser: the padlock shows a valid Let's Encrypt certificate, and the app shell loads. Plain HTTP redirects to HTTPS. The pilot smoke test also passes against the on-premise address:

```powershell
python deploy/pilot/smoke_test.py $Url
```

Then run it end to end as the test learner: it signs in, uploads a one-page PDF, chooses a subject, waits until the document is ready, asks about it, and requires a citation of that PDF. It deletes the document at the end, also when a step fails (a document that is still processing can't be deleted; delete it from the Library later). The conversation stays, and the subject "Smoke testing" may be added to the shared catalog once. Use only the test learner.

```powershell
$Learner = aws secretsmanager get-secret-value --secret-id smart-tutor-on-premise/keycloak/test-learner --query SecretString --output text | ConvertFrom-Json
$env:SMOKE_TEST_USERNAME = $Learner.username
$env:SMOKE_TEST_PASSWORD = $Learner.password
python deploy/pilot/smoke_test.py $Url --end-to-end
Remove-Item Env:SMOKE_TEST_USERNAME, Env:SMOKE_TEST_PASSWORD; Remove-Variable Learner
```

The first upload after a deploy takes a minute or two (the worker describes and embeds it with Bedrock). If it fails, read `dc logs --tail 100 worker` (section 6). Keep `--deadline-seconds` under 900: the access token lasts 15 minutes and isn't refreshed.

2. **Only 80 and 443 are open.** `Test-NetConnection` reports `TcpTestSucceeded : False` for SSH:

```powershell
Test-NetConnection (Get-Output PublicIp) -Port 22 | Select-Object TcpTestSucceeded
```

3. **Sign in as the test learner.** Read the credentials and don't paste them anywhere:

```powershell
aws secretsmanager get-secret-value --secret-id smart-tutor-on-premise/keycloak/test-learner --query SecretString --output text
```

Open `$Url` in a private window, choose **Sign in**, and sign in as `test-learner@example.com`. The Library shows "Test Learner" in the user menu. In DevTools → Application → Cookies, `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` are **Secure**, which proves Keycloak trusts Caddy's `X-Forwarded-Proto`. The `/api/me` request returns 200.

4. **Admin console.** `$Url/auth/admin`, as the bootstrap admin in `smart-tutor-on-premise/keycloak/admin`. Create learners' accounts as in `pilot-deploy.md` §8. If you delete the bootstrap admin, later deploys skip the sign-in client and test-learner checks and print a warning.

## 5. Redeploy

Run step 3 again with another `$Tag`.

- **A new tag:** it pulls the new images and migrates, then Compose recreates only the services whose image or settings changed. Postgres and Caddy keep running (unless their settings changed). Expect a short gap in sign-in while Keycloak restarts.
- **The same tag:** nothing changes. Migrations are already at head, every container keeps running, and the test learner already exists.
- **A rotated secret** (for example `smart-tutor-on-premise/db/app`): the redeploy resets the role's password to the new value and recreates the services that read it.
- **To roll back:** deploy an older SHA. Migrations don't run backwards, so only roll back across commits without a schema change, or restore the database (`on-premise-backups.md`).

## 6. Operate the VM

There is no SSH. Open a shell through Session Manager:

```powershell
aws ssm start-session --target $InstanceId
```

```bash
sudo -i
cd /opt/smart-tutor/on-premise
dc() { docker compose --env-file /etc/smart-tutor/smart-tutor.env "$@"; }
dc ps                       # status and health of every service
dc logs --tail 100 api      # each service keeps 5 log files of 10 MB
dc restart keycloak
```

Never run `dc config` or `cat` on the env file in a session that someone records: both print secrets.

**Worker isolation.** `deploy.sh` checks it on every deploy; to check by hand:

```bash
docker inspect --format 'user={{.Config.User}} readonly={{.HostConfig.ReadonlyRootfs}} capdrop={{.HostConfig.CapDrop}} secopt={{.HostConfig.SecurityOpt}}' "$(dc ps -q worker)"
```

It prints `user=10001:10001 readonly=true capdrop=[ALL] secopt=[no-new-privileges:true]`. The worker parses each PDF in a child process, which it stops after `SMART_TUTOR_EXTRACTION_TIMEOUT_SECONDS` (300); the document then fails with "This PDF took too long to read". Each extraction starts a fresh Python interpreter, and its start-up counts toward the limit.

**Worker egress.** The worker sits on an internal Compose network with no route out of the VM. It reaches Postgres directly. Everything else goes through `egress-proxy` (Squid), which allows only the documents bucket, SQS, SSM, and Bedrock runtime in the region, and the instance metadata service, by exact name. `deploy.sh` proves this on every deploy; to run the check by hand:

```bash
dc exec -T worker python - < /opt/smart-tutor/on-premise/check-egress.py
```

It exits 0 when the worker reaches nothing it must not and everything it needs. It exits 1 (or crashes) when the worker reached something it must not, or the check couldn't run: the deploy stops the worker. It exits 2 when a needed destination is unreachable: the deploy fails, and the worker keeps running. The proxy's log shows what it refused: `dc logs --tail 50 egress-proxy`; `TCP_DENIED/403` lines are refused requests. To let the worker reach a new AWS endpoint, add it to the `acl aws` line in `compose.yaml`; until then the deploy check fails. The proxy image is pinned by digest; to bump it, pull the tag (`docker pull ubuntu/squid:6.6-24.04_edge`), read its digest with `docker image inspect --format '{{index .RepoDigests 0}}' ubuntu/squid:6.6-24.04_edge`, and replace the image's `@sha256:` part in `compose.yaml` with it.

**Dead-letter drill.** A message the worker fails on 5 times moves to `smart-tutor-on-premise-ingest-dlq`. To check the redrive, stop the worker so it doesn't take the message, send one, receive it 5 times without deleting it, and look in the DLQ. From your laptop, with `dc stop worker` done on the VM first:

```powershell
$Queue = aws sqs get-queue-url --queue-name smart-tutor-on-premise-ingest --query QueueUrl --output text
$Dlq = aws sqs get-queue-url --queue-name smart-tutor-on-premise-ingest-dlq --query QueueUrl --output text
aws sqs send-message --queue-url $Queue --message-body '{"poisoned": true}' | Out-Null
1..6 | ForEach-Object { aws sqs receive-message --queue-url $Queue --visibility-timeout 0 --wait-time-seconds 5 --query "Messages[0].Attributes.ApproximateReceiveCount" --attribute-names ApproximateReceiveCount --output text }
aws sqs get-queue-attributes --queue-url $Dlq --attribute-names ApproximateNumberOfMessages --query Attributes.ApproximateNumberOfMessages --output text
```

The receive counts go 1 to 5, the sixth receive returns nothing (`None`), and the DLQ holds 1 message (the count can lag a minute). Then purge the DLQ (`aws sqs purge-queue --queue-url $Dlq`) and run `dc start worker` on the VM. In normal running, a message lands there when processing crashes 5 times (Bedrock, S3, or database errors); `dc logs worker` shows why.

**Services restart by themselves.** Every service has a health check and `restart: unless-stopped`. After a reboot, Docker waits for `/data` to be mounted before it starts them.

**Resize the instance.** Change `smart-tutor:on-premise-instance-type` in `infra/cdk.json` (for example to `t3.xlarge`) and run step 2. CloudFormation stops the instance, changes its type, and starts it again. The data volume stays attached, and the services come back on their own.

**Replace the instance.** CloudFormation replaces the instance when its image changes. The AMI is the latest Amazon Linux 2023, read at each `cdk deploy`, so a deploy after Amazon publishes a new image replaces the VM. The data survives:

1. CloudFormation starts the new instance and moves the Elastic IP to it. The new instance waits for the data volume, which the old instance holds until CloudFormation terminates it at the end of the update.
2. Once it has the volume, the new instance mounts it (it doesn't format a volume that has a file system) and installs Docker.
3. Then run step 3. The database, Keycloak's users, and Caddy's certificates are as they were. The deploy waits up to 15 minutes for `/data`.

The data volume keeps a snapshot if the stack is deleted (`DeletionPolicy: Snapshot`). The instance is also replaced when its user data changes, for example a new Compose version or a data volume restored from a snapshot (`on-premise-backups.md`).

## 7. Tear down

```powershell
Push-Location infra
npx aws-cdk@latest destroy SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise
Pop-Location
```

This deletes the VM, the Elastic IP, and the VPC. The data volume is deleted after a final snapshot. Note the `DataVolumeId` output before you destroy, and delete that volume's snapshot by hand when the data must go (EC2 → Snapshots, filter by volume id). The Storage stack keeps the documents bucket, as in native-cloud. No other stack references the Host (Storage's CORS names the configured domain or `*.sslip.io`, not the Elastic IP), so the Host can be destroyed on its own. The DuckDNS token's secret isn't part of any stack, so it stays. When the Host is deployed again, its first deploy points the name at the new Elastic IP.

## 8. DuckDNS name (#154)

`smart-tutor.duckdns.org` is a free DuckDNS subdomain. The DuckDNS account belongs to the Google account `dtrungthao@gmail.com`: sign in at [duckdns.org](https://www.duckdns.org) with it to see the token, regenerate it, or change the address by hand. Whoever takes over the pilot needs that account, or a new subdomain in an account of their own (then follow "Switch the domain").

**Store the token** once, and again after regenerating it on duckdns.org. Paste it at the prompt; it isn't echoed or kept in the shell history:

```powershell
$Token = Read-Host -AsSecureString "DuckDNS token"
aws secretsmanager create-secret --name smart-tutor-on-premise/duckdns/token `
    --description "DuckDNS token for smart-tutor.duckdns.org (deploy.sh points the name at the Elastic IP)" `
    --secret-string (ConvertFrom-SecureString $Token -AsPlainText)
Remove-Variable Token
```

To replace a stored token, run `aws secretsmanager put-secret-value --secret-id smart-tutor-on-premise/duckdns/token --secret-string ...` the same way. The instance reads it with its role (`smart-tutor-on-premise/*`). It isn't in CDK, so tearing down the Host keeps it.

**Each deploy** (section 3, and every deploy on merge):

- Points the name at the instance: DuckDNS records the address the request comes from, which is the Elastic IP. The output says `Pointed smart-tutor.duckdns.org at this instance`. `Warning: could not update ...` means the secret is missing or the token is wrong. The deploy goes on, and the name keeps its old address.
- Points the sign-in client (`smart-tutor-web`) at the domain when it changed: redirect URIs, web origins, and post-logout redirect URIs. The output says `Pointed the sign-in client at https://<domain>` once after a change.

Check that the name resolves to the Elastic IP:

```powershell
(Resolve-DnsName smart-tutor.duckdns.org -Type A).IPAddress
Get-Output PublicIp
```

**Switch the domain** (another DuckDNS name, or empty for `<Elastic IP>.sslip.io`): change `smart-tutor:on-premise-domain` in `infra/cdk.json`, deploy the stacks (section 2: the Storage stack's CORS, the Host's `domain` setting, and the uptime check follow it), and deploy an image tag (section 3). For another DuckDNS name, store its account's token first. Caddy requests a certificate for the new name. Learners signed in at the old address sign in again, because the token issuer changes with it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `send-command` fails with `InvalidInstanceId` | The SSM agent isn't registered yet, or the instance is still in its first boot. Wait for `Online` (step 2). The first-boot log is `/var/log/cloud-init-output.log`. |
| `/data is not mounted` | The data volume is still attached to a replaced instance. Wait until CloudFormation finishes the update and run the deploy again. |
| The browser warns about the certificate | Caddy couldn't get one: `dc logs caddy`. Let's Encrypt needs port 80 open (it is in the security group) and the domain to resolve to the Elastic IP (section 8). sslip.io names resolve to the IP they contain. Too many attempts hit Let's Encrypt's rate limits; the certificate is kept on `/data/caddy`, so replacing the VM doesn't request a new one. |
| `docker compose up` times out on `keycloak` | The first start creates the schema and imports the realm, which takes up to 3 minutes. Check `dc logs keycloak`. |
| Sign-in says "Invalid parameter: redirect_uri" | The `smart-tutor-web` client doesn't list the domain. Keycloak imports the realm once, and each deploy points the client at the domain (section 8), so run a deploy. If it printed `could not check the sign-in client`, the bootstrap admin is gone: set the client's redirect URIs, web origins, and post-logout redirect URIs in the admin console. |
| `Warning: could not update <domain> on DuckDNS` | The secret `smart-tutor-on-premise/duckdns/token` is missing, or its token isn't the account's current one (section 8). The name keeps its old address: if the Elastic IP changed, sign-in and the certificate fail until it's fixed. |
| `The worker is not isolated: ...` (deploy or patch window fails) | `compose.yaml` lost one of the worker's `user`, `read_only`, `cap_drop`, or `security_opt` settings. The check stops the worker, so uploads wait in the queue. Restore the settings and deploy again; never run the worker without them. |
| `Stopped the worker: the egress check found a leak or could not run (see above)` (deploy or patch window fails) | The output above names the host the worker reached (lines `The worker can reach what it must not: ...`) or the error that kept the check from running. A reached host means `compose.yaml` lost the worker's `networks: [worker]`, or the proxy's rules allow more than they should. The worker is stopped, so uploads wait in the queue. Restore the file and deploy again. The weekly patch window runs the same checks. |
| `The worker cannot reach a destination it needs` (deploy fails) | `dc logs egress-proxy` shows `TCP_DENIED` for a host the worker needs (a new endpoint: add it to `acl aws`), or AWS answered with errors. The worker keeps running. |
| A document stays processing | The worker isn't running or can't reach AWS: `dc ps worker`, `dc logs --tail 100 worker`, `dc logs --tail 50 egress-proxy`. `AccessDenied` means the instance role lacks a permission (Host stack); a Bedrock `ThrottlingException` retries on its own. |
| `Warning: could not check the sign-in client or the test learner` | The bootstrap admin was deleted. The deploy still succeeded. Create the test learner by hand if you need it. After a domain change, set the sign-in client's addresses by hand too (row "Invalid parameter: redirect_uri"). |
