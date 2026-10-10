#!/usr/bin/env bash
# Deploys one image tag on the on-premise VM (#148, ADR 0012). SSM Run Command runs it as root through the document
# <prefix>-deploy (HostStack), after unpacking the deploy bundle to /opt/smart-tutor:
#   SMART_TUTOR_PREFIX=smart-tutor-on-premise AWS_REGION=us-east-1 deploy.sh <full commit SHA>
#
# 1. Renders settings (SSM) and secrets (Secrets Manager) into a root-only env file.
# 2. Pulls the images, starts Postgres, and creates or updates the app and Keycloak roles and databases.
# 3. Migrates, then starts every service and waits until all are healthy. Compose recreates only the services whose
#    image or settings changed, so the same tag again changes nothing. Fails unless the running worker is isolated
#    (non-root, read-only root, no capabilities; a worker that isn't is stopped) and the agent and MCP server answer.
#    Installs and enables the scheduled jobs' systemd units (the nightly backup, #151).
# 4. Creates the test learner if it is missing.
#
# It prints no secret: never add `set -x`, `docker compose config`, or an echo of the env file.
set -euo pipefail

tag=${1:?usage: deploy.sh <full commit SHA>}
[[ $tag =~ ^[0-9a-f]{40}$ ]] || { echo "The image tag must be a full 40-character commit SHA" >&2; exit 2; }
prefix=${SMART_TUTOR_PREFIX:?names the SSM path and secrets of the mode}
region=${AWS_REGION:?}
here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/smart-tutor/smart-tutor.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")

param() { aws ssm get-parameter --name "/$prefix/$1" --query Parameter.Value --output text; }
secret() { aws secretsmanager get-secret-value --secret-id "$prefix/$1" --query SecretString --output text; }
field() { python3 -c 'import json, sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"; }

# A new instance attaches the data volume at first boot, after the instance it replaced lets go of it.
for _ in $(seq 90); do mountpoint -q /data && break; sleep 10; done
mountpoint -q /data || { echo "/data is not mounted: the data volume isn't attached (see the instance's user data log)" >&2; exit 1; }
mkdir -p /data/postgres /data/caddy/data /data/caddy/config

echo "Reading settings and secrets for $prefix"
domain=$(param host/domain)
registry=$(param host/registry)
documents_bucket=$(param host/documents-bucket)
ingest_queue_url=$(param host/ingest-queue-url)
postgres_password=$(secret db/postgres)
app_db_password=$(secret db/app)
# Built here, not written out in compose.yaml: a URL of the form user:password@host in the repository looks like a
# leaked credential to secret scanners (GitGuardian), even when the password is a ${PLACEHOLDER}.
app_database_url=$(printf 'postgresql+psycopg://%s@postgres:5432/smart_tutor' "smart_tutor:$app_db_password")
keycloak_db_password=$(secret db/keycloak)
keycloak_admin=$(secret keycloak/admin)
keycloak_admin_username=$(field username <<<"$keycloak_admin")
keycloak_admin_password=$(field password <<<"$keycloak_admin")
api_client_secret=$(secret keycloak/api-client)
mcp_client_secret=$(secret keycloak/mcp-client)
test_learner=$(secret keycloak/test-learner)
caddyfile_sha256=$(sha256sum "$here/Caddyfile" | cut -d' ' -f1)

umask 077
mkdir -p "$(dirname "$env_file")"
rendered=$(mktemp "$env_file.XXXXXX")
cat > "$rendered" <<EOF
IMAGE_TAG=$tag
REGISTRY=$registry
DOMAIN=$domain
AWS_REGION=$region
SSM_PATH=/$prefix
DOCUMENTS_BUCKET=$documents_bucket
INGEST_QUEUE_URL=$ingest_queue_url
CADDYFILE_SHA256=$caddyfile_sha256
POSTGRES_PASSWORD=$postgres_password
APP_DB_PASSWORD=$app_db_password
APP_DATABASE_URL=$app_database_url
KEYCLOAK_DB_PASSWORD=$keycloak_db_password
KEYCLOAK_ADMIN_USERNAME=$keycloak_admin_username
KEYCLOAK_ADMIN_PASSWORD=$keycloak_admin_password
API_CLIENT_SECRET=$api_client_secret
MCP_CLIENT_SECRET=$mcp_client_secret
EOF
mv "$rendered" "$env_file"

echo "Pulling $tag from $registry"
aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry" >/dev/null
"${compose[@]}" pull --quiet

echo "Starting Postgres and bootstrapping the databases"
"${compose[@]}" up -d --wait postgres
# The same idempotent script as native-cloud's Helm hook; it also resets each role's password to its secret.
{
  printf '\\getenv app_password APP_DB_PASSWORD\n\\getenv keycloak_password KEYCLOAK_DB_PASSWORD\n'
  cat "$here/../helm/smart-tutor/files/db-bootstrap.sql"
} | "${compose[@]}" exec -T postgres psql -q -U postgres -d postgres \
  -v app_user=smart_tutor -v app_db=smart_tutor -v keycloak_user=keycloak -v keycloak_db=keycloak >/dev/null

echo "Migrating"
"${compose[@]}" run --rm migrate

echo "Starting the services"
"${compose[@]}" up -d --wait --wait-timeout 900 --remove-orphans

# The worker parses untrusted PDFs: fail the deploy unless the running container really is isolated, whatever
# compose.yaml says (an override file or a hand-started container would otherwise go unnoticed).
echo "Checking the worker's isolation"
worker=$("${compose[@]}" ps -q worker)
[[ -n $worker ]] || { echo "The worker container is not running" >&2; exit 1; }
isolation=$(docker inspect --format \
  '{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{json .HostConfig.CapDrop}}|{{json .HostConfig.SecurityOpt}}' "$worker")
IFS='|' read -r user readonly_rootfs cap_drop security_opt <<<"$isolation"
problems=()
[[ $user == 10001:10001 ]] || problems+=("runs as '$user', not 10001:10001")
[[ $readonly_rootfs == true ]] || problems+=("ReadonlyRootfs is $readonly_rootfs")
[[ $cap_drop == *'"ALL"'* ]] || problems+=("CapDrop $cap_drop does not drop ALL")
[[ $security_opt == *'"no-new-privileges:true"'* ]] || problems+=("SecurityOpt $security_opt lacks no-new-privileges")
if ((${#problems[@]})); then
  printf 'The worker is not isolated: %s\n' "${problems[@]}" >&2
  # Don't leave it consuming uploads after the deploy is marked failed.
  docker stop "$worker" >/dev/null
  echo "Stopped the worker" >&2
  exit 1
fi

# The agent and MCP server have no public route; check them from inside the API container, as the API reaches them.
echo "Checking the agent and the MCP server"
"${compose[@]}" exec -T api python -c "import urllib.request as u; u.urlopen('http://agent:8080/healthz', timeout=10)"
"${compose[@]}" exec -T api python -c "
import urllib.error as e, urllib.request as u
try:
    u.urlopen('http://mcp:8000/mcp', timeout=10)
except e.HTTPError as x:
    raise SystemExit(0 if x.code == 401 else f'MCP answered {x.code} without a token, expected 401')
raise SystemExit('MCP answered without a token')"

# Scheduled jobs are systemd timers that call `docker compose run` (docs/runbooks/on-premise-backups.md). The units
# read the env file rendered above, so they start only after the first deploy.
echo "Installing the scheduled jobs"
install -m 644 "$here"/systemd/* /etc/systemd/system/
systemctl daemon-reload
for timer in "$here"/systemd/*.timer; do
  systemctl enable --now --quiet "$(basename "$timer")"
done

# The test learner is created once (the realm uses the email as the username) and gets the secret's password while it
# has none; later changes go through the admin console. The script reaches the container on stdin, so the password is
# on no command line outside it. A missing bootstrap admin (deleted after the first sign-in, as the runbook allows)
# skips the check instead of failing the deploy.
learner_username=$(field username <<<"$test_learner")
learner_password=$(field password <<<"$test_learner")
if ! "${compose[@]}" exec -T keycloak bash -s <<EOF
set -euo pipefail
kc() { /opt/keycloak/bin/kcadm.sh "\$@" --config /tmp/kcadm.config; }
learner_id() { kc get users -r smart-tutor -q exact=true -q username=$learner_username --fields id --format csv --noquotes; }
trap 'rm -f /tmp/kcadm.config' EXIT
kc config credentials --server http://localhost:8080/auth --realm master \
  --user "\$KC_BOOTSTRAP_ADMIN_USERNAME" --password "\$KC_BOOTSTRAP_ADMIN_PASSWORD" >/dev/null 2>&1
id=\$(learner_id)
if [ -z "\$id" ]; then
  kc create users -r smart-tutor -s username=$learner_username -s email=$learner_username -s emailVerified=true \
    -s enabled=true -s firstName=Test -s lastName=Learner >/dev/null 2>&1
  id=\$(learner_id)
  echo "Created the test learner $learner_username"
fi
if ! kc get "users/\$id/credentials" -r smart-tutor --fields type --format csv --noquotes | grep -qx password; then
  kc set-password -r smart-tutor --username $learner_username --new-password $learner_password >/dev/null 2>&1
  echo "Set the password of the test learner"
fi
EOF
then
  echo "Warning: could not check the test learner (is Keycloak's bootstrap admin still there?)" >&2
fi

docker image prune -af >/dev/null
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Deployed $tag to https://$domain"
