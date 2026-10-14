#!/usr/bin/env bash
# Dumps the app and Keycloak databases to the on-premise bucket (#151). The `phoenix` database (traces, ADR 0017) is
# left out: losing traces on a restore is acceptable. smart-tutor-backup.timer runs it as root every
# night; deploy.sh installs the timer. Runbook: docs/runbooks/on-premise-backups.md.
#
#   s3://<documents bucket>/backups/postgres/<UTC timestamp>/{smart_tutor,keycloak}.dump   (pg_dump custom format)
#
# The bucket expires backups/ after 30 days. A failure exits non-zero and is in journalctl -u smart-tutor-backup (no alarm,
# ADR 0022). It prints no secret.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/smart-tutor/smart-tutor.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")
# One non-secret value of the env file deploy.sh renders.
setting() { sed -n "s/^$1=//p" "$env_file"; }

bucket=$(setting DOCUMENTS_BUCKET)
export AWS_REGION; AWS_REGION=$(setting AWS_REGION)
stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
work=/data/backups/$stamp  # pg-dump sees /data/backups as /backups

umask 077
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

# Every dump is written before any is uploaded, so a failed night leaves no half backup in the bucket.
for db in smart_tutor keycloak; do
  "${compose[@]}" run --rm -T pg-dump --file="/backups/$stamp/$db.dump" "$db"
done
for db in smart_tutor keycloak; do
  aws s3 cp --only-show-errors "$work/$db.dump" "s3://$bucket/backups/postgres/$stamp/$db.dump"
done

echo "Backed up smart_tutor ($(du -h "$work/smart_tutor.dump" | cut -f1)) and keycloak" \
  "($(du -h "$work/keycloak.dump" | cut -f1)) to s3://$bucket/backups/postgres/$stamp/"
