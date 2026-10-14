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

There is no backup alarm (ADR 0022). Check the backups by hand (next section) after a deploy, a restore, or anything unusual. A failed dump is in the VM's journal: `journalctl -u smart-tutor-backup -n 100`. A failed snapshot shows in **EC2 → Lifecycle Manager → the policy → Monitoring**. The host is off 18:00–07:00, so the 03:00 dump runs at the 07:00 start (`Persistent=true`); the 02:00 snapshot works on the stopped instance.

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

1. **Pick the snapshot** (see "Check the backups"). Note its id, `snap-…`. If it is one of the policy's daily snapshots, the policy deletes it after 7 days; that is fine once the volume exists, but copy it (EC2 → Snapshots → Copy) if you may need to restore from it again later.
2. **Set it in `infra/cdk.json`** through a PR: `"smart-tutor:on-premise-data-snapshot-id": "snap-…"`. **Never pass it with `-c` to a `cdk deploy` by hand:** the next merge deploys `cdk.json` and replaces the restored volume with a blank one (the drill lost a restored volume this way; its final snapshot kept the data). Preview the change from `infra/` with `npx aws-cdk@2.1145.0 diff SmartTutor-OnPremise-prod-Host --exclusively -c smart-tutor:mode=on-premise`: it creates `DataVolumeFrom<snapshot id>` and a new `Instance`, and destroys the old volume and instance. **Leave it set afterwards.** Changing it again restores another snapshot, and clearing it replaces the volume with a **blank** one. CloudFormation snapshots every volume it deletes, so even that mistake can be undone the same way.
3. **Merge the PR.** The deploy on merge (`on-premise-deploy.md` §3) does the rest. CloudFormation creates the volume from the snapshot as a new resource (an in-place update is something EC2 refuses), starts a new instance that attaches it, and moves the Elastic IP. It then terminates the old instance and deletes the old volume after a final snapshot of it. The workflow waits for the new VM, deploys the merged commit's images (migrations only move forward, so a snapshot from an older schema is migrated up), and runs the smoke test. The final snapshot has no description and isn't managed by the policy: delete it by hand once the restore is checked.
4. **Check:** a learner signs in and their library and threads are as they were at the snapshot time. Caddy keeps its certificate (it is on the volume).

A volume restored from a snapshot loads its blocks from S3 the first time each is read, so the first minutes are slow. If a `cdk deploy` of the Host stack fails and its rollback fails too (`UPDATE_ROLLBACK_FAILED`), every later deploy fails until you recover it: see Troubleshooting.

## Restore from a `pg_dump` onto a fresh VM

Use this when the volume and its snapshots are gone (the Host stack was destroyed, the account lost them), or to recover a single bad night's change from up to 30 days back. You lose the data written since that dump.

1. **A running VM with an empty database.** If the Host stack is gone, deploy the stacks and a tag (`on-premise-deploy.md` §2 and §4, with `smart-tutor:on-premise-data-snapshot-id` empty). If the stack is there but its volume is lost or not to be trusted, set the snapshot id to `""` in `infra/cdk.json` through a PR (or to `"snap-…"` → `""` if it held one): the merge gives a blank volume and a new VM, deploys, and passes the smoke test with an empty database. The deploy creates the roles and databases, and the restore needs them. A blank volume has no certificate, so Caddy requests one; Let's Encrypt issues at most 5 for the same name a week.
2. **Pick the dump** (`aws s3 ls "s3://$Bucket/backups/postgres/"`). The timestamp is the folder name, for example `2026-10-09T200312Z`.
3. **Restore it** in a Session Manager shell:

   ```bash
   sudo bash /opt/smart-tutor/on-premise/restore.sh 2026-10-09T200312Z
   ```

   It downloads both dumps (nothing changes if either is missing), stops every service but Postgres, then drops and recreates `smart_tutor` and `keycloak` from the dumps. The product is down from here until step 4.
4. **Deploy the same image tag again** (`on-premise-deploy.md` §4). It resets the roles' passwords to the secrets, migrates the restored schema to head, and starts the services.
5. **Check:** a learner signs in with their old password, and their library and threads are back. The test learner has the password from the dump. If the Elastic IP changed, the deploy points the DuckDNS name at the new one (`on-premise-deploy.md` section 9); with the sslip.io fallback the address changes too, and the deploy points the sign-in client at it. Caddy requests a new certificate if `/data/caddy` was lost.

Documents follow the database, not the bucket. Documents uploaded after the backup are missing from the library, though their files stay in the bucket. Documents deleted after it come back in the library, but their PDF is gone. Restore the PDF's previous version in S3 if it is needed.

## Restore drill

The PRD asks for one drill before the pilot starts, while the database holds only test data. A drill runs both paths: a snapshot onto a new volume, and a dump onto a fresh VM. Each replaces the data written since its backup.

1. **Make data you can recognize.** As the test learner, upload a document and ask about it, and keep both: `deploy/pilot/smoke_test.py --end-to-end` deletes its document, so upload through the app. Create a second account in the admin console.
2. **Fingerprint the data** on the VM, so a restore can be compared with it exactly:

   ```bash
   dc exec -T postgres psql -U postgres -d smart_tutor -At -c "select format('select %L, count(*) from public.%I', table_name, table_name) from information_schema.tables where table_schema='public' and table_type='BASE TABLE' order by 1" \
     | while read -r q; do dc exec -T postgres psql -U postgres -d smart_tutor -At -c "$q" < /dev/null; done
   dc exec -T postgres psql -U postgres -d smart_tutor -At -c "select md5(string_agg(thread_id::text, ',' order by thread_id)) from threads"
   dc exec -T postgres psql -U postgres -d smart_tutor -At -c "select md5(string_agg(document_id::text, ',' order by document_id)) from documents"
   dc exec -T postgres psql -U postgres -d keycloak -At -c "select count(*), md5(string_agg(u.username, ',' order by u.username)) from user_entity u join realm r on r.id = u.realm_id where r.name <> 'master'"
   ```

   (`< /dev/null` matters: without it `dc exec` reads the rest of the loop's input.) It prints row counts and hashes, never a learner's data.
3. **Back up:** `systemctl start smart-tutor-backup` (note the timestamp it prints), then snapshot the data volume (EC2 → Volumes → the `DataVolumeId` output → Create snapshot).
4. **Snapshot path:** "Restore from a snapshot" with that snapshot. Fingerprint again: it must equal step 2.
5. **Dump path:** "Restore from a `pg_dump` onto a fresh VM" with that dump, starting from a blank volume. Fingerprint again: it must equal step 2.
6. After each path, the second account is listed in the admin console, the document opens from the Library, its thread is listed, and the end-to-end smoke test passes (`on-premise-deploy.md` §5).

Record each drill:

| Date | Path | Backup | Result | By |
|---|---|---|---|---|
| 2026-10-11 | Snapshot, `cdk deploy -c …snapshot-id` by hand | `snap-0463b98fe3c21b1d3` | **Failed.** CloudFormation updated `SnapshotId` in place, which EC2 refuses; the rollback failed the same way and left the Host stack in `UPDATE_ROLLBACK_FAILED` (recovered as in Troubleshooting; the volume was never changed). Fixed in #240: a restored volume is a new resource | Claude Code for the product owner |
| 2026-10-11 | Snapshot, by hand, after the fix | `snap-0463b98fe3c21b1d3` | Volume and instance replaced in 2.5 min (CloudFormation 08:18:46–08:21:16 UTC). **Not checked:** a merge (#229) deployed `cdk.json` 17 minutes later and replaced the restored volume with a blank one; its final snapshot kept the data. Hence step 2 of "Restore from a snapshot" | Claude Code for the product owner |
| 2026-10-11 | Dump onto a fresh VM (the blank volume above) | `2026-10-11T025404Z` | **Passed.** `restore.sh` 42 s, the redeploy of the same tag about 2 min, so the product was down about 3 minutes. The fingerprint equals the backup's (11 tables, 2 Keycloak accounts, thread and document ids). The document opens, its thread is listed, and the end-to-end smoke test passed. Caddy got a new certificate | Claude Code for the product owner |
| 2026-10-11 | Snapshot through a `cdk.json` PR (#240) | `snap-0a78e35899360960f` | **Passed.** The deploy on merge took 5.5 min (09:49:54–09:55:23 UTC), CloudFormation 2 min of it: it created `DataVolumeFromsnap-0a78e35899360960f` and a new VM, then deleted the old volume after its final snapshot. The fingerprint equals the snapshot's (11 tables, 2 Keycloak accounts, thread and document ids). The document opens, both threads are listed, and the end-to-end smoke test passed. Caddy kept its certificate. Afterwards the drill's account and its own snapshots were deleted | Claude Code for the product owner |

## Scheduled jobs on the VM (timer pattern)

On-premise has no Kubernetes CronJobs. A scheduled job is a **systemd timer** on the VM that starts a **one-off Compose container**: `systemd timer → service → docker compose run --rm <job>`. The backup is the first such job. The retention sweeps (`smart_tutor.apps.jobs.retention`) and the learning-record sweeper (`record_sweeper`) follow the same pattern when they move to on-premise. To add one:

1. **Compose service** in `deploy/on-premise/compose.yaml`, in the `jobs` profile so `up` never starts it, with the shared log rotation:

   ```yaml
   retention:
     image: ${REGISTRY:?}/${REPOSITORY_PREFIX:?}/api:${IMAGE_TAG:?}
     profiles: [jobs]
     logging: *logging
     command: ["python", "-m", "smart_tutor.apps.jobs.retention"]
     environment: { ... }   # the settings it needs, from the env file like the api service
     depends_on:
       postgres: {condition: service_healthy}
   ```

2. **Service unit** `deploy/on-premise/systemd/smart-tutor-<job>.service`. A failure stays in the unit's journal:

   ```ini
   [Unit]
   Description=Smart Tutor: <what it does>
   Requires=docker.service
   After=docker.service

   [Service]
   Type=oneshot
   ExecStart=/usr/bin/docker compose --project-directory /opt/smart-tutor/on-premise -f /opt/smart-tutor/on-premise/compose.yaml --env-file /etc/smart-tutor/smart-tutor.env run --rm -T <job>
   TimeoutStartSec=1h
   ```

   A job that needs more than one container, or a step on the host (such as the upload in `backup.sh`), runs a script instead: `ExecStart=/usr/bin/bash /opt/smart-tutor/on-premise/<job>.sh`.
3. **Timer unit** `smart-tutor-<job>.timer` with `OnCalendar=` in UTC, `Persistent=true`, and `WantedBy=timers.target` (copy `smart-tutor-backup.timer`).
4. **Deploy.** `deploy.sh` installs every unit in `deploy/on-premise/systemd/` and enables every timer. Check on the VM with `systemctl list-timers 'smart-tutor-*'`. Removing a unit file doesn't disable the timer on the VM: run `systemctl disable --now smart-tutor-<job>.timer` there too.

Keep in mind:

- The job's container gets the same settings and instance-profile credentials as the long-running services. It reads the env file through Compose; never print it.
- `deploy.sh` replaces `/opt/smart-tutor` on every deploy, so a job that starts during a deploy can fail. The run then fails once, and the next run is normal.
- The host is off 18:00–07:00 (ADR 0022). Give the timer `Persistent=true` so a run missed while it was off happens at the next start.
- systemd times are UTC here. Write the local time (Asia/Ho_Chi_Minh, UTC+7) in a comment.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `journalctl -u smart-tutor-backup` shows `AccessDenied` on `s3 cp` | The bucket name or prefix changed. The role may write only `smart-tutor-on-premise-documents-<account>/backups/*` (Host stack). |
| `pg_dump: error: connection … failed` | Postgres isn't healthy: `dc ps`, `dc logs postgres`. |
| `No space left on device` | The dumps are written to `/data/backups` before the upload. Check `df -h /data` and grow the volume. |
| The timer isn't listed | No deploy has run since #151, or the env file is missing. Run a deploy. |
| `restore.sh` fails in `pg_restore` | A database may be half restored. Fix the cause (the error is above it) and run it again: it drops and recreates each database. The services stay stopped until a deploy. |
| The Host stack is `UPDATE_ROLLBACK_FAILED`, and every deploy fails | An update and its rollback both failed on one resource, for example the data volume before #155 (EC2 refuses to change a volume's snapshot in place). Check that the resource itself is unchanged (for the volume: `aws ec2 describe-volumes --volume-ids <DataVolumeId>` shows it still attached to the instance), then skip it in the rollback: `aws cloudformation continue-update-rollback --stack-name SmartTutor-OnPremise-prod-Host --resources-to-skip <logical id>` and `aws cloudformation wait stack-rollback-complete --stack-name SmartTutor-OnPremise-prod-Host`. Re-run the failed deploy (Actions → deploy). |
