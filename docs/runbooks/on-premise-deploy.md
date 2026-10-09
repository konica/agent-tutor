# On-premise deploy (#148)

Deploys on-premise mode (ADR 0012, PRD §9.12): one EC2 VM runs Smart Tutor with Docker Compose, and Caddy serves it over HTTPS at `https://<Elastic IP>.sslip.io` with a Let's Encrypt certificate. This runbook covers the first deploy and a manual redeploy. It currently brings up Postgres, Keycloak, the API, the web app, and Caddy, so a learner can sign in. The worker, agent, and MCP server, and with them upload and ask, come in #149. Deploy on merge is #150. Backups and restore: `on-premise-backups.md` (#151). Alarms and weekly patching: `on-premise-monitoring.md` (#152); after the first deploy, every alert recipient confirms the subscription email.

Commands are for **PowerShell 7** (`pwsh`). Run them from the repository root with your admin profile. No command here prints a secret. Don't paste the values you read in step 4 anywhere.

## What runs where

| Piece | Where |
|---|---|
| CDK stacks `SmartTutor-OnPremise-prod-*` | `infra/` with `-c smart-tutor:mode=on-premise` (the default mode): Storage, Config, Budgets, GitHubDeploy, and **Host** (`infra/smart_tutor_infra/stacks/host.py`) |
| Images | ECR `smart-tutor/<service>:<commit SHA>`, shared with native-cloud (its Registry stack owns the repositories) |
| Files on the VM | `deploy/` is uploaded as a CDK asset; the deploy unpacks it to `/opt/smart-tutor` and runs `/opt/smart-tutor/on-premise/deploy.sh` |
| Settings and secrets | SSM `/smart-tutor-on-premise/*` and Secrets Manager `smart-tutor-on-premise/*`. On the VM, `deploy.sh` renders them into `/etc/smart-tutor/smart-tutor.env` (root only, mode 600) |
| Data | The data volume, mounted at `/data`: Postgres in `/data/postgres` (the app and Keycloak databases), and Caddy's certificates in `/data/caddy` |

The Host stack creates a VPC with one public subnet, no NAT, and an S3 gateway endpoint. It also creates a `t3.large` Amazon Linux 2023 instance with no SSH key and a security group that admits TCP 80 and 443 only, plus an Elastic IP and a 50 GB encrypted gp3 data volume. The SSM document `smart-tutor-on-premise-deploy` runs the deploy. The instance size is the context `smart-tutor:on-premise-instance-type` in `infra/cdk.json`. The domain is `smart-tutor:on-premise-domain`: empty means `<Elastic IP>.sslip.io`, and #154 switches it to DuckDNS.

## 1. Before you start

- CDK is bootstrapped in the account (`pilot-aws-prerequisites.md` §2), and the GitHub OIDC provider exists (native-cloud's `SmartTutor-prod-GitHubDeploy` created it; the on-premise deploy role reuses it).
- The ECR repositories exist (`SmartTutor-prod-Registry`) and hold images for the commit you want. Every merge to `main` pushes them, tagged with the full commit SHA. On-premise needs `api`, `web`, and `keycloak`.
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
foreach ($Repo in "api", "web", "keycloak") {
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
4. It creates the test learner if it is missing.

The output lists each service's status and ends with `Deployed <tag> to https://...`. It never contains a secret.

## 4. Check

1. **Certificate and routes.** Open `$Url` in a browser: the padlock shows a valid Let's Encrypt certificate, and the app shell loads. Plain HTTP redirects to HTTPS. The pilot smoke test also passes against the on-premise address:

```powershell
python deploy/pilot/smoke_test.py $Url
```

2. **Only 80 and 443 are open.** `Test-NetConnection` reports `TcpTestSucceeded : False` for SSH:

```powershell
$Ip = ([uri]$Url).Host -replace '\.sslip\.io$', ''
Test-NetConnection $Ip -Port 22 | Select-Object TcpTestSucceeded
```

3. **Sign in as the test learner.** Read the credentials and don't paste them anywhere:

```powershell
aws secretsmanager get-secret-value --secret-id smart-tutor-on-premise/keycloak/test-learner --query SecretString --output text
```

Open `$Url` in a private window, choose **Sign in**, and sign in as `test-learner@example.com`. The Library shows "Test Learner" in the user menu. In DevTools → Application → Cookies, `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` are **Secure**, which proves Keycloak trusts Caddy's `X-Forwarded-Proto`. The `/api/me` request returns 200.

4. **Admin console.** `$Url/auth/admin`, as the bootstrap admin in `smart-tutor-on-premise/keycloak/admin`. Create learners' accounts as in `pilot-deploy.md` §8. If you delete the bootstrap admin, later deploys skip the test-learner check and print a warning.

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

This deletes the VM, the Elastic IP, and the VPC. The data volume is deleted after a final snapshot. Note the `DataVolumeId` output before you destroy, and delete that volume's snapshot by hand when the data must go (EC2 → Snapshots, filter by volume id). The Storage stack keeps the documents bucket, as in native-cloud.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `send-command` fails with `InvalidInstanceId` | The SSM agent isn't registered yet, or the instance is still in its first boot. Wait for `Online` (step 2). The first-boot log is `/var/log/cloud-init-output.log`. |
| `/data is not mounted` | The data volume is still attached to a replaced instance. Wait until CloudFormation finishes the update and run the deploy again. |
| The browser warns about the certificate | Caddy couldn't get one: `dc logs caddy`. Let's Encrypt needs port 80 open (it is in the security group) and the domain to resolve to the Elastic IP. sslip.io names resolve to the IP they contain. Too many attempts hit Let's Encrypt's rate limits; the certificate is kept on `/data/caddy`, so replacing the VM doesn't request a new one. |
| `docker compose up` times out on `keycloak` | The first start creates the schema and imports the realm, which takes up to 3 minutes. Check `dc logs keycloak`. |
| Sign-in says "Invalid parameter: redirect_uri" | The domain changed after the realm was imported. Keycloak imports the realm once, so update the `smart-tutor-web` client's redirect URIs, web origins, and post-logout redirect URIs in the admin console (#154). |
| `Warning: could not check the test learner` | The bootstrap admin was deleted. The deploy still succeeded; create the test learner by hand if you need it. |
