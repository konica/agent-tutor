# On-premise backups and restore (#151)

On-premise mode keeps PDFs and page text in the versioned documents bucket. The VM holds only PostgreSQL: the app database `smart_tutor` and Keycloak's `keycloak` (users, sessions, the realm). This runbook covers how the database is backed up, how to check the backups, how to restore it in two ways, the restore drill, and the pattern for scheduled jobs on the VM.

Commands are for **PowerShell 7** with the shell set up as in `on-premise-deploy.md` §1. Commands marked `bash` run on the VM in a Session Manager shell (`on-premise-deploy.md` §7). No command here prints a secret.

## What is backed up

| Backup | When (UTC) | Kept | Where | Defined in |
|---|---|---|---|---|
| **EBS snapshot** of the data volume (`/data`: Postgres and Caddy's certificates) | Daily 19:00 (02:00 in Ho Chi Minh City) | 7 days | EC2 → Snapshots, tag `smart-tutor:snapshots=smart-tutor-on-premise-prod` | Data Lifecycle Manager policy in the Host stack |
| **`pg_dump`** of `smart_tutor` and `keycloak` (custom format) | Nightly 20:00, up to 10 minutes later | 30 days | `s3://smart-tutor-on-premise-documents-<account>/backups/postgres/<timestamp>/` | `smart-tutor-backup.timer` → `deploy/on-premise/backup.sh`; lifecycle rule in the Storage stack |

Together they lose at most one day of data. A snapshot is crash-consistent: Postgres recovers it like a restart after a power cut. A dump is consistent, and it survives losing the volume, its snapshots, or the stack. The instance role can write only the `backups/` prefix of the bucket.

The dumps hold learner data (threads, notes) and Keycloak's users. They are encrypted at rest (SSE-S3), the bucket blocks public access, and they expire after 30 days. Don't copy them anywhere else.

## Alerts

The Host stack has an SNS topic `smart-tutor-on-premise-prod-alerts` that emails the addresses in `smart-tutor:budget-alert-emails`. **After the first `cdk deploy`, each address gets an "AWS Notification - Subscription Confirmation" email: confirm it, or no alert arrives.**

| Alarm | Fires when | First look |
|---|---|---|
| `…-BackupFailedAlarm…` | `backup.sh` failed or timed out (1 h). systemd's `OnFailure=` runs `smart-tutor-job-failed@smart-tutor-backup`, which publishes `SmartTutor/OnPremise JobFailed` | `bash`: `journalctl -u smart-tutor-backup -n 100` |
| `…-SnapshotFailedAlarm…` | Data Lifecycle Manager couldn't create the daily snapshot (`AWS/EBS SnapshotsCreateFailed`) | EC2 → Lifecycle Manager → the policy → Monitoring; the policy's role is `…-SnapshotRole…` |

Each alarm emails once when it fires and goes back to OK by itself an hour later. Silence doesn't prove that backups ran. If the VM was down at 20:00, the timer runs the backup as soon as the VM is back (`Persistent=true`). Monitoring (#152) covers a VM that is down.

## Check the backups

```powershell
$Account = aws sts get-caller-identity --query Account --output text
$Bucket = "smart-tutor-on-premise-documents-$Account"

# Snapshots, newest last
aws ec2 describe-snapshots --owner-ids self --filters "Name=tag:smart-tutor:snapshots,Values=smart-tutor-on-premise-prod" `
    --query "sort_by(Snapshots,&StartTime)[].{Id: SnapshotId, Started: StartTime, State: State}" --output table

# Dumps: one folder per night, each with smart_tutor.dump and keycloak.dump
aws s3 ls "s3://$Bucket/backups/postgres/"
aws s3 ls "s3://$Bucket/backups/postgres/<timestamp>/"
```

On the VM:

```bash
systemctl list-timers smart-tutor-backup.timer   # next and last run
systemctl start smart-tutor-backup               # back up now (waits until done)
journalctl -u smart-tutor-backup -n 20           # ends with "Backed up smart_tutor (…) and keycloak (…) to s3://…"
```

## Restore from a snapshot

Use this when the volume or the database on it is damaged and a snapshot from before the damage is good enough. You lose the data written since that snapshot. A new volume is created from the snapshot, and the instance is replaced so its first boot attaches it, as in `on-premise-deploy.md` §7 "Replace the instance".

1. **Pick the snapshot** (see "Check the backups"). Note its id, `snap-…`.
2. **Set it in `infra/cdk.json`:** `"smart-tutor:on-premise-data-snapshot-id": "snap-…"`. Commit it to `main` through a PR, because every deploy reads `cdk.json`. **Leave it set afterwards.** Changing it again replaces the volume again, and clearing it replaces the restored volume with a **blank** one. CloudFormation snapshots the volume it replaces, so even that mistake can be undone the same way.
3. **Deploy the Host stack.** The deploy on merge does this. To do it by hand:

   ```powershell
   Push-Location infra
   npx aws-cdk@latest diff SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise   # Volume and Instance: replace
   npx aws-cdk@latest deploy SmartTutor-OnPremise-prod-Host -c smart-tutor:mode=on-premise
   Pop-Location
   ```

   CloudFormation creates the volume from the snapshot and starts a new instance that attaches it, then moves the Elastic IP. It terminates the old instance and deletes the old volume after taking a final snapshot of it. That final snapshot isn't managed by the policy: delete it by hand once the restore is checked.
4. **Deploy an image tag** (`on-premise-deploy.md` §4, with the new `$InstanceId`). Use the tag that is running now: migrations only move forward, so a snapshot from an older schema is migrated up.
5. **Check:** a learner signs in and their library and threads are as they were at the snapshot time. Caddy keeps its certificate (it is on the volume).

A volume restored from a snapshot loads its blocks from S3 the first time each is read, so the first minutes are slow.

## Restore from a `pg_dump` onto a fresh VM

Use this when the volume and its snapshots are gone (the Host stack was destroyed, the account lost them), or to recover a single bad night's change from up to 30 days back. You lose the data written since that dump.

1. **A running VM with an empty database.** If the Host stack is gone, deploy the stacks and a tag (`on-premise-deploy.md` §2 and §4, with `smart-tutor:on-premise-data-snapshot-id` empty). The deploy creates the roles and databases, and the restore needs them.
2. **Pick the dump** (`aws s3 ls "s3://$Bucket/backups/postgres/"`). The timestamp is the folder name, for example `2026-10-09T200312Z`.
3. **Restore it** in a Session Manager shell:

   ```bash
   sudo bash /opt/smart-tutor/on-premise/restore.sh 2026-10-09T200312Z
   ```

   It downloads both dumps (nothing changes if either is missing), stops every service but Postgres, then drops and recreates `smart_tutor` and `keycloak` from the dumps. The product is down from here until step 4.
4. **Deploy the same image tag again** (`on-premise-deploy.md` §4). It resets the roles' passwords to the secrets, migrates the restored schema to head, and starts the services.
5. **Check:** a learner signs in with their old password, and their library and threads are back. The test learner has the password from the dump. A new Elastic IP means a new `<ip>.sslip.io` address: the restored realm still lists the old one, so sign-in says "Invalid parameter: redirect_uri". Fix it as in `on-premise-deploy.md` Troubleshooting (a DuckDNS name, #154, avoids this). Caddy requests a new certificate.

Documents follow the database, not the bucket. Documents uploaded after the backup are missing from the library, though their files stay in the bucket. Documents deleted after it come back in the library, but their PDF is gone. Restore the PDF's previous version in S3 if it is needed.

## Restore drill

The PRD asks for one drill before the pilot starts, while the database holds only test data. The drill restores the newest dump onto the running VM (step 3 onwards above), which replaces today's changes:

1. Sign in as the test learner and make changes you can recognize: create a learner account in the admin console, and once uploads work (#149), upload a document and start a thread.
2. `systemctl start smart-tutor-backup`, and note the timestamp it prints.
3. Undo the changes: delete the account, the document, and the thread.
4. Run `restore.sh` with that timestamp, then deploy the same tag.
5. The account signs in again, and the document and thread are back. The document opens at a citation.
6. Optionally, run the snapshot path the same way with today's snapshot.

Record each drill:

| Date | Path | Backup | Result | By |
|---|---|---|---|---|
| | | | | |

## Scheduled jobs on the VM (timer pattern)

On-premise has no Kubernetes CronJobs. A scheduled job is a **systemd timer** on the VM that starts a **one-off Compose container**: `systemd timer → service → docker compose run --rm <job>`. The backup is the first such job. The retention sweeps (`smart_tutor.apps.jobs.retention`) and the learning-record sweeper (`record_sweeper`) follow the same pattern when they move to on-premise. To add one:

1. **Compose service** in `deploy/on-premise/compose.yaml`, in the `jobs` profile so `up` never starts it, with the shared log rotation:

   ```yaml
   retention:
     image: ${REGISTRY:?}/smart-tutor/api:${IMAGE_TAG:?}
     profiles: [jobs]
     logging: *logging
     command: ["python", "-m", "smart_tutor.apps.jobs.retention"]
     environment: { ... }   # the settings it needs, from the env file like the api service
     depends_on:
       postgres: {condition: service_healthy}
   ```

2. **Service unit** `deploy/on-premise/systemd/smart-tutor-<job>.service`. `OnFailure=` reports a failure, and `%N` is the unit's name without `.service`:

   ```ini
   [Unit]
   Description=Smart Tutor: <what it does>
   Requires=docker.service
   After=docker.service
   OnFailure=smart-tutor-job-failed@%N.service

   [Service]
   Type=oneshot
   ExecStart=/usr/bin/docker compose --project-directory /opt/smart-tutor/on-premise -f /opt/smart-tutor/on-premise/compose.yaml --env-file /etc/smart-tutor/smart-tutor.env run --rm -T <job>
   TimeoutStartSec=1h
   ```

   A job that needs more than one container, or a step on the host (such as the upload in `backup.sh`), runs a script instead: `ExecStart=/usr/bin/bash /opt/smart-tutor/on-premise/<job>.sh`.
3. **Timer unit** `smart-tutor-<job>.timer` with `OnCalendar=` in UTC, `Persistent=true`, and `WantedBy=timers.target` (copy `smart-tutor-backup.timer`).
4. **Alarm** in the Host stack: a `JobFailed` alarm with `Job=smart-tutor-<job>`, like `BackupFailedAlarm`.
5. **Deploy.** `deploy.sh` installs every unit in `deploy/on-premise/systemd/` and enables every timer. Check on the VM with `systemctl list-timers 'smart-tutor-*'`. Removing a unit file doesn't disable the timer on the VM: run `systemctl disable --now smart-tutor-<job>.timer` there too.

Keep in mind:

- The job's container gets the same settings and instance-profile credentials as the long-running services. It reads the env file through Compose; never print it.
- `deploy.sh` replaces `/opt/smart-tutor` on every deploy, so a job that starts during a deploy can fail. The alarm then fires once, and the next run is normal.
- systemd times are UTC here. Write the local time (Asia/Ho_Chi_Minh, UTC+7) in a comment.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `journalctl -u smart-tutor-backup` shows `AccessDenied` on `s3 cp` | The bucket name or prefix changed. The role may write only `smart-tutor-on-premise-documents-<account>/backups/*` (Host stack). |
| `pg_dump: error: connection … failed` | Postgres isn't healthy: `dc ps`, `dc logs postgres`. |
| `No space left on device` | The dumps are written to `/data/backups` before the upload. Check `df -h /data` and grow the volume. |
| The timer isn't listed | No deploy has run since #151, or the env file is missing. Run a deploy. |
| `restore.sh` fails in `pg_restore` | A database may be half restored. Fix the cause (the error is above it) and run it again: it drops and recreates each database. The services stay stopped until a deploy. |
| No alert email although the alarm is in ALARM | The subscription is unconfirmed: SNS → Topics → `…-alerts` → Subscriptions. Request the confirmation again there. |
