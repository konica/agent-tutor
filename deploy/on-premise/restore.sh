#!/usr/bin/env bash
# Restores the app and Keycloak databases from one nightly dump (#151), replacing what is in them now. Run it as root on
# the VM after at least one deploy (which creates the roles), then deploy again (docs/runbooks/on-premise-backups.md):
#   bash /opt/smart-tutor/on-premise/restore.sh 2026-10-09T200312Z
#
# It stops every service but Postgres, so the product is down until the next deploy starts them. It prints no secret.
set -euo pipefail

stamp=${1:?usage: restore.sh <backup timestamp, for example 2026-10-09T200312Z>}
[[ $stamp =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z$ ]] || { echo "Not a backup timestamp: $stamp" >&2; exit 2; }
here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/smart-tutor/smart-tutor.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")
setting() { sed -n "s/^$1=//p" "$env_file"; }

bucket=$(setting DOCUMENTS_BUCKET)
export AWS_REGION; AWS_REGION=$(setting AWS_REGION)
work=/data/backups/restore-$stamp

umask 077
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

# Both files first: a missing one stops the restore before anything changes.
for db in smart_tutor keycloak; do
  aws s3 cp --only-show-errors "s3://$bucket/backups/postgres/$stamp/$db.dump" "$work/$db.dump"
done

echo "Stopping every service but Postgres"
"${compose[@]}" stop
"${compose[@]}" up -d --wait postgres

# --create with --clean drops each database and creates it again from the dump, with its owner, extensions (pgvector),
# and grants. The roles are the deploy's (db-bootstrap.sql); the next deploy resets their passwords to the secrets.
for db in smart_tutor keycloak; do
  echo "Restoring $db from $stamp"
  "${compose[@]}" exec -T postgres pg_restore -U postgres -d postgres --clean --if-exists --create --exit-on-error \
    < "$work/$db.dump"
done

echo "Restored $stamp. Run the deploy (SSM document <prefix>-deploy) to migrate and start the services."
