# Off-hours hosts and a shared Langfuse host — Design

- Date: 2026-10-14
- Status: draft, for review
- PRD: §9.10 (risks), §9.11 Hosting, §9.12 Environments, infrastructure as code, and delivery, Appendix (on-premise resources)
- ADRs: 0012 (on-premise default), 0016 (deployment modes share no stack), 0017 (Phoenix, superseded in part by 0021 below)

## 1. Why

- **Cost.** The product owner wants both on-premise hosts stopped when learners aren't expected: **00:00–07:00 and 18:00–24:00, Asia/Ho_Chi_Minh (GMT+7), every day**. They run 07:00–18:00.
- **Langfuse.** The product owner chose Langfuse to manage the full lifecycle of observability and evaluation, replacing LangSmith and Phoenix (2026-10-14). It runs on **its own host in its own stack**, so other apps can use the same Langfuse later.
- **No CloudWatch alarms.** They cost money, and with a daily stop the uptime alarm would email twice a day. The product owner decided to remove all four of the app host's alarms and add none.

## 2. Outcome and success

- Both hosts stop at 18:00 and start at 07:00 local time with no manual step.
- **A person can start either host by hand at any hour, and the app works as normal.**
- No weekly patching run and no nightly dump is lost to the stop.
- Langfuse deploys and is destroyed without touching any Smart Tutor stack, and its project and stacks don't mention Smart Tutor.

Not in scope:
- Wiring Smart Tutor to Langfuse (tracing, ratings, API keys) and moving the evals off LangSmith. That is the **Langfuse migration**, which follows this work (it unblocks #302).
- Native-cloud mode: it isn't deployed.
- A "closed" page at night. The DuckDNS name points straight at the host's Elastic IP, so after 18:00 a browser gets a connection error. The hours are stated in the PRD.
- Trace retention (D25, 180 days). Self-hosted Langfuse sets retention per project (`LANGFUSE_INIT_PROJECT_RETENTION`, the project settings), and its docs list data-retention policies among the Enterprise features. The migration's ADR settles it.

## 3. Structure

| Path | What |
|---|---|
| `infra/` | Smart Tutor's CDK app. `SmartTutor-OnPremise-Host` stays the app host's stack; it gains `OffHours`, loses its alarms, and moves its patch window. |
| `platform/langfuse/` | **New**, a CDK project of its own: `pyproject.toml` (uv), `cdk.json`, `app.py`, `langfuse_platform/` (stack and constructs), `tests/`, and `deploy/` (Compose file, Caddyfile, `deploy.sh`, `ensure-healthy.sh`). One stack: `Langfuse-Host`. |

- `platform/` holds services several apps can share. Moving `platform/langfuse/` to a repository of its own later is a folder move.
- Neither project references the other's stacks, SSM parameters, or secrets. Apps reach Langfuse over HTTPS with a per-project API key (the migration).
- `OffHours` is a small construct (about 80 lines). Each project keeps **its own copy**: a shared package between two projects costs more than the copy, and another app may want different hours.
- CI (`.github/workflows/ci.yml`) runs `cd platform/langfuse && uv run pytest` when `platform/` changes, as it runs `infra` tests when `infra/` changes.

## 4. The `OffHours` construct

`OffHours(scope, id, *, instance, name_prefix, time_zone="Asia/Ho_Chi_Minh")`

- One EventBridge Scheduler **schedule group** `<name_prefix>-off-hours` and three schedules, all with `schedule_expression_timezone = time_zone`, flexible time window off, and a retry policy of 2 attempts:

| Schedule | Expression | Target (universal target) | Input |
|---|---|---|---|
| `stop` | `cron(0 18 * * ? *)` | `arn:aws:scheduler:::aws-sdk:ec2:stopInstances` | `{"InstanceIds": ["<id>"]}` |
| `stop-late` | `cron(0 0 * * ? *)` | `arn:aws:scheduler:::aws-sdk:ec2:stopInstances` | `{"InstanceIds": ["<id>"]}` |
| `start` | `cron(0 7 * * ? *)` | `arn:aws:scheduler:::aws-sdk:ec2:startInstances` | `{"InstanceIds": ["<id>"]}` |

- `stop-late` stops a host that someone started by hand in the evening, matching the product owner's two "off" windows. Stopping a stopped instance, or starting a running one, is a no-op.
- **One IAM role** per host, assumed only by `scheduler.amazonaws.com` with `aws:SourceAccount` = the account. It allows `ec2:StartInstances` and `ec2:StopInstances` on **that instance's ARN only**. Both hosts' volumes use the AWS-managed `aws/ebs` key, whose key policy already lets EC2 use it on behalf of any principal in the account, so the role needs no KMS permission. A customer-managed key would need `kms:CreateGrant` here.
- No dead-letter queue and no alarm. A failed call is retried twice. EventBridge Scheduler's free CloudWatch metrics (`InvocationAttemptCount`, `TargetErrorCount`) show failures to anyone who looks.

### 4.1 A stop is a clean shutdown

`StopInstances` shuts the OS down: systemd stops Docker, and Docker stops each container with its stop signal and grace period.
- **Postgres** (both hosts) and **ClickHouse** (Langfuse) get `stop_grace_period: 60s`. The default 10 s can cut a shutdown short and leave crash recovery for the next start. The Postgres image's stop signal is already `SIGINT` (fast shutdown).
- The app host's worker already has 60 s (it finishes its current poll).

### 4.2 Starting by hand

- `aws ec2 start-instances --instance-ids <id>` or the EC2 console. The runbooks list both, with the command that reads the id from the stack output.
- A boot at any hour is the same as the 07:00 boot:
  - the data volume mounts from `/etc/fstab`, and Docker waits for it (`RequiresMountsFor=/data`);
  - every container has `restart: unless-stopped`, so Docker brings the whole stack up;
  - the Elastic IP stays associated through a stop, so the DuckDNS name, Caddy's certificates, and Keycloak's hostname still match;
  - work that waited runs: SQS keeps uploads (the worker processes them), and the nightly dump timer (`Persistent=true`) runs if its 03:00 run was missed.
- **The app host never needs the Langfuse host**, and the reverse holds too. Either starts alone; tracing failures never fail a request (ADR 0017's rule carries over to Langfuse).
- **The 00:00 stop still applies.** To keep a host up overnight, the operator disables `stop-late` and turns it back on afterwards:
  `aws scheduler update-schedule --group-name <prefix>-off-hours --name stop-late --state DISABLED ...` (the runbook has the full command, which must repeat the schedule's settings).
- A deploy still running at 18:00 is cut off. The deploy runbooks say: deploy before 17:30, or after starting the host by hand.

## 5. App host changes (`infra/smart_tutor_infra/stacks/host.py`)

- **Add** `OffHours(self, "OffHours", instance=instance, name_prefix=names.resource_prefix)`.
- **Remove** the four CloudWatch alarms and what only they used:
  - `UptimeAlarm` and the Route 53 `UptimeCheck` health check;
  - `RecoveryAlarm`. EC2's simplified automatic recovery, on by default for t3, still moves the instance off failed hardware; it no longer emails.
  - `BackupFailedAlarm` and `SnapshotFailedAlarm`;
  - the `JobFailed` metric: `deploy/on-premise/report-failure.sh`, the `smart-tutor-job-failed@.service` unit and the backup unit's `OnFailure=`, and the instance role's `PublishJobMetrics` statement. A failed dump is in `journalctl -u smart-tutor-backup`.
- **Keep** the `<prefix>-alerts` SNS topic and its email subscriptions, used only by the EventBridge rule that emails when the patch window fails or times out. That rule is not a CloudWatch alarm.
- **Move** the patch window from Sunday 04:00 to **Sunday 07:20** (`cron(20 7 ? * SUN *)`, app time zone): twenty minutes after the start, so Docker has the services up; it reboots only when a patch needs it, then `ensure-healthy.sh` checks every service.
- **Unchanged:** the DLM snapshot at 02:00 (snapshots work on a stopped instance's volume) and the dump timer at 03:00 (`Persistent=true` runs it at the next boot).
- `deploy/on-premise/compose.yaml`: Postgres gains `stop_grace_period: 60s`.

## 6. The Langfuse host (`platform/langfuse`, stack `Langfuse-Host`)

### 6.1 Settings (`platform/langfuse/cdk.json` context)

| Key | Default | Meaning |
|---|---|---|
| `langfuse:region` | `us-east-1` | Region of the stack |
| `langfuse:instance-type` | `t3.xlarge` | 4 vCPU, 16 GiB (Langfuse's Compose minimum) |
| `langfuse:domain` | empty | Its DuckDNS name; empty means `<eip>.sslip.io` |
| `langfuse:alert-emails` | `[]` | Who gets the patch-failure email |
| `langfuse:data-snapshot-id` | empty | Restore the data volume from a snapshot (as the app host) |

Names use the fixed prefix `langfuse` (resources), `Langfuse-` (stacks), and `/langfuse` (SSM and Secrets Manager paths).

### 6.2 Network and instance

- A VPC of its own, `10.42.0.0/16`, one AZ, one public subnet, no NAT, an S3 gateway endpoint.
- Security group: TCP 80 (ACME HTTP-01 and the HTTPS redirect) and 443 from anywhere; no SSH, no key pair (SSM Session Manager).
- Amazon Linux 2023, x86_64, IMDSv2 required with hop limit 2 (containers use the instance role), an Elastic IP, a 30 GiB encrypted gp3 root volume.
- Instance role: `AmazonSSMManagedInstanceCore`, read its bundle, read `/langfuse/*` parameters and secrets, attach its tagged data volume, and read/write its bucket.

### 6.3 Data and backups

- A **100 GiB** encrypted gp3 data volume mounted at `/data` (Postgres, ClickHouse, Caddy's certificates), attached at first boot by id, exactly as the app host does, so it outlives a replaced instance. `RemovalPolicy.SNAPSHOT`.
- Data Lifecycle Manager snapshots it daily at 02:00 local (19:00 UTC) and keeps 7 days. That covers traces, scores (human reviews), and datasets. No database dump: a restore is a volume from a snapshot (runbook).
- An S3 bucket `langfuse-<account>-<region>`: private, SSE-S3, TLS-only, versioning off, `RemovalPolicy.RETAIN`. CORS allows PUT and GET from the Langfuse origin (media uploads use presigned URLs). Langfuse writes event batches under `events/` and media under `media/`; batch export stays off.

### 6.4 Containers (`platform/langfuse/deploy/compose.yaml`)

Every image is pinned to an exact version, never a floating tag such as Langfuse's own `:4` or `redis:7`. The plan picks the newest release of each line that is at least two weeks old, and the test checks that no tag floats. Every service has `restart: unless-stopped` and a memory limit.

| Service | Image line | Memory | Notes |
|---|---|---|---|
| `langfuse-web` | `langfuse/langfuse` v4 | 2 GiB | the only service Caddy proxies (`:3000`) |
| `langfuse-worker` | `langfuse/langfuse-worker` v4, same version as web | 2 GiB | |
| `clickhouse` | `clickhouse/clickhouse-server` 25.12 or newer (Langfuse v4's minimum) | 6 GiB | single node: `CLICKHOUSE_CLUSTER_ENABLED=false`; `stop_grace_period: 60s` |
| `postgres` | `postgres` 17 | 1 GiB | `stop_grace_period: 60s` |
| `valkey` | `valkey/valkey` 8 | 512 MiB | `--requirepass`, `--maxmemory 384mb --maxmemory-policy noeviction` |
| `caddy` | `caddy` 2.11 alpine, as the app host | 128 MiB | ports 80 and 443; certificate from Let's Encrypt |

About 11.6 GiB of the 16 GiB; the rest is the OS, Docker, and the page cache ClickHouse and Postgres use.

Langfuse settings:
- `NEXTAUTH_URL=https://<domain>`, `NEXTAUTH_SECRET`, `SALT`, `ENCRYPTION_KEY` (64 hex characters), `DATABASE_URL`, `CLICKHOUSE_*`, `REDIS_*` from the secrets below.
- S3: `LANGFUSE_S3_EVENT_UPLOAD_*` and `LANGFUSE_S3_MEDIA_UPLOAD_*` point at the bucket with region set, `FORCE_PATH_STYLE=false`, and **no access keys**: the AWS SDK falls back to the instance role (Langfuse's docs recommend an IAM role on AWS). The plan's first task checks this on a real instance before the rest is built; if it fails, an IAM user's keys in Secrets Manager are the fallback.
- `AUTH_DISABLE_SIGNUP=true` and `TELEMETRY_ENABLED=false`.
- Headless initialization creates one organization, one project, and its admin user: `LANGFUSE_INIT_ORG_ID`, `LANGFUSE_INIT_PROJECT_ID`, `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`/`SECRET_KEY`, `LANGFUSE_INIT_USER_EMAIL`/`PASSWORD`. Other people: the admin invites them, and because sign-up is off, the runbook turns `AUTH_DISABLE_SIGNUP` off for one deploy while they create their account, then back on.

### 6.5 Secrets and deploy

- Generated in Secrets Manager under `langfuse/`: `nextauth-secret`, `salt`, `encryption-key` (operator-set to `openssl rand -hex 32` at first deploy, because Secrets Manager can't generate hex), `db/postgres`, `clickhouse`, `valkey`, `admin` (email and password), `init-project-keys`. The operator stores the DuckDNS token as `langfuse/duckdns-token`.
- `cdk deploy` uploads `platform/langfuse/deploy/` as an asset. An SSM Command document `langfuse-deploy` downloads it and runs `deploy.sh`, which:
  - waits for first boot (`cloud-init status --wait`);
  - renders the secrets into a root-only env file (never on a command line or in the template);
  - points the DuckDNS name at the Elastic IP when a domain is set;
  - runs `docker compose pull` and `docker compose up -d --remove-orphans`, then `ensure-healthy.sh`.
- The operator runs it with one runbook command (`aws ssm send-command --document-name langfuse-deploy ...`). No GitHub workflow yet.

### 6.6 Operations

- `OffHours` (its own copy), same schedules as the app host.
- Weekly patching: baseline (security updates), maintenance window Sunday 07:20 local, `AWS-RunPatchBaseline` (reboot if needed), then `ensure-healthy.sh`. An EventBridge rule emails `langfuse-alerts` when the window fails or times out.
- No CloudWatch alarms. EC2's default automatic recovery handles failed hardware.

## 7. Documents changed in the same PR

- **PRD** (bump v2.62 → v2.63):
  - §9.11 and §9.12: the on-premise product is available **07:00–18:00 Asia/Ho_Chi_Minh, every day**, and stopped outside those hours; monitoring loses the recovery alarm, uptime check, and backup alarms; patching moves to Sunday 07:20.
  - §9.10: the single-VM risk's mitigation no longer names alarms; add "the product is off 18:00–07:00".
  - Appendix: Host stack resources (no recovery alarm).
- **ADR 0021 — Langfuse for observability and evaluation, on a shared host in its own CDK project.** Records the product owner's choice; supersedes ADR 0017's choice of tool (Phoenix stays until the migration lands); why its own host (t3.xlarge; it doesn't fit beside the app on the t3.large) and its own project (reuse by other apps); what the migration still decides (D25 retention, moving the evals, connecting the app).
- **ADR 0022 — On-premise hosts run 07:00–18:00 and carry no CloudWatch alarms.** The schedule, `stop-late`, manual starts, the clean shutdown, and what we lose without alarms: nobody is emailed when the site is down, a dump fails, or a snapshot fails.
- **Runbooks:**
  - `docs/runbooks/on-premise-monitoring.md`: alarms removed; the schedule; starting by hand; keeping the host up overnight; reading a failed dump from `journalctl`; the scheduler's metrics.
  - `docs/runbooks/on-premise-backups.md`: alarm references removed.
  - `docs/runbooks/on-premise-deploy.md` and `pilot-deploy.md`: deploy before 17:30, or start the host first.
  - **New** `docs/runbooks/langfuse-host.md`: first deploy (secrets, encryption key, DuckDNS token), first admin sign-in, adding a person, deploy and upgrade, starting by hand, patching, restoring from a snapshot.
- **`AGENTS.md`**: a `platform/` row in the repository map and the `platform/langfuse` test command in Checks. **Structure spec** (`sdd/specs/2026-10-02-project-structure-design.md`): the `platform/` folder.

## 8. Testing

Unit tests on the synthesized templates (CDK assertions), as `infra/tests` does today:

- **`infra/tests/test_host.py`**
  - three `AWS::Scheduler::Schedule` resources in `Asia/Ho_Chi_Minh` with the expressions above, each targeting the EC2 universal target with this instance's id;
  - the scheduler role's policy allows only `ec2:StartInstances`/`ec2:StopInstances` on this instance's ARN, and only `scheduler.amazonaws.com` assumes it;
  - no `AWS::CloudWatch::Alarm` and no `AWS::Route53::HealthCheck`; no `PublishJobMetrics` statement;
  - the patch window's schedule is `cron(20 7 ? * SUN *)` in the app time zone.
- **Compose test** (`infra/tests`, reading `deploy/on-premise/compose.yaml`): Postgres has `stop_grace_period: 60s`; every long-running service has `restart: unless-stopped`.
- **`platform/langfuse/tests`**
  - template: VPC and security group (80 and 443 only), instance type from context, data volume and DLM policy, bucket (private, encrypted, TLS-only), secrets under `langfuse/`, the deploy document, the three schedules, no alarms, and no string `smart-tutor` anywhere in the template;
  - Compose file: every image pinned to an exact version, every service with a memory limit and `restart: unless-stopped`, Postgres and ClickHouse with `stop_grace_period: 60s`, `AUTH_DISABLE_SIGNUP=true`, `CLICKHOUSE_CLUSTER_ENABLED=false`, no S3 access key variables, and only Caddy publishing ports.

Checked by hand after deploying (recorded in the PR):
1. `cdk diff` of both projects shows only the expected changes.
2. After 18:00 both instances are `stopped` and the app is unreachable; after 07:00, `https://<domain>/api/healthz` returns 200 within 5 minutes and Langfuse's sign-in page loads.
3. The app host started by hand at night is healthy within 5 minutes, and the 00:00 stop stops it.
4. The app host alone works with Langfuse stopped; Langfuse alone works with the app host stopped.
5. Langfuse: the admin signs in, the init project exists, and an event and a media upload land in the bucket (the instance-role check).

## 9. Cost

Running 11 hours a day (on-demand, us-east-1):

| Item | Per month |
|---|---|
| t3.large app host | about $27 |
| t3.xlarge Langfuse host | about $55 |
| gp3: 80 GiB (app) + 130 GiB (Langfuse) | about $17 |
| Two Elastic IPs (charged running or stopped) | about $7 |
| EventBridge Scheduler (about 180 invocations), DLM, snapshots | under $2 |
| **Total** | **about $110** |

The account budget (`smart-tutor:budget-monthly-usd`, $20) is below this, so its emails keep firing. The product owner sets the new amount; this work doesn't change it.

## 10. Order of work

1. **Spike (throwaway):** Langfuse v4 on a t3.xlarge with the instance role and no S3 keys. Confirms the S3 credential fallback and that headless init works with sign-up off.
2. **App host:** `OffHours`, alarms removed, patch window moved, Postgres grace period, runbooks, PRD, ADR 0022.
3. **Langfuse project:** scaffolding, CI, the stack, the Compose bundle, `deploy.sh`, `OffHours` copy, runbook, ADR 0021, AGENTS.md and the structure spec.
4. **Deploy and check by hand** (§8).

Steps 2 and 3 are separate PRs; step 2 can merge first and starts saving money at once.
