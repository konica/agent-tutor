#!/usr/bin/env bash
# Deploys Langfuse on the Langfuse host (spec 2026-10-14 §6.5, ADR 0021). SSM Run Command runs it as root through the
# document langfuse-deploy (LangfuseHostStack), after unpacking the bundle to /opt/langfuse:
#   AWS_REGION=us-east-1 bash /opt/langfuse/deploy.sh
#
# 1. Renders settings (SSM /langfuse/host/*) and secrets (Secrets Manager langfuse/*) into a root-only env file.
# 2. Points a DuckDNS domain at this instance's Elastic IP.
# 3. Gives Docker two minutes to stop the containers when the instance stops.
# 4. Pulls the pinned images, starts every service, and waits until all are healthy. The same bundle again changes
#    nothing.
#
# It prints no secret: never trace the shell, print the rendered Compose configuration, or echo the env file.
set -euo pipefail

region=${AWS_REGION:?}
here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/langfuse/langfuse.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")

param() { aws ssm get-parameter --name "/langfuse/host/$1" --query Parameter.Value --output text; }
secret() { aws secretsmanager get-secret-value --secret-id "langfuse/$1" --query SecretString --output text; }
field() { python3 -c 'import json, sys; print(json.loads(sys.stdin.read())[sys.argv[1]])' "$1"; }
# 64 hex characters from a label and a generated secret: Secrets Manager can't generate hex, and Langfuse's
# ENCRYPTION_KEY must be 64 hex characters. The same secret always gives the same key; never rotate encryption-seed.
hex64() { printf '%s:%s' "$1" "$2" | sha256sum | cut -d' ' -f1; }

# A new instance attaches the data volume at first boot, after the instance it replaced lets go of it.
for _ in $(seq 90); do mountpoint -q /data && break; sleep 10; done
mountpoint -q /data || { echo "/data is not mounted: the data volume isn't attached (see the instance's user data log)" >&2; exit 1; }
mkdir -p /data/postgres /data/clickhouse /data/clickhouse-logs /data/valkey /data/caddy/data /data/caddy/config
chown 101:101 /data/clickhouse /data/clickhouse-logs  # ClickHouse runs as 101:101

echo "Reading settings and secrets"
domain=$(param domain)
bucket=$(param bucket)
if [[ $(param allow-signup) == true ]]; then auth_disable_signup=false; else auth_disable_signup=true; fi
postgres_password=$(secret db/postgres)
# Built here, not written out in compose.yaml: a user:password@host URL in the repository looks like a leaked
# credential to secret scanners.
database_url=$(printf 'postgresql://%s@postgres:5432/postgres' "postgres:$postgres_password")
clickhouse_password=$(secret clickhouse)
redis_auth=$(secret valkey)
nextauth_secret=$(secret nextauth-secret)
salt=$(secret salt)
encryption_seed=$(secret encryption-seed)
encryption_key=$(hex64 encryption "$encryption_seed")
project_seed=$(secret init-project-keys)
init_public_key="pk-lf-$(hex64 public "$project_seed" | cut -c1-32)"
init_secret_key="sk-lf-$(hex64 secret "$project_seed" | cut -c1-32)"
admin=$(secret admin)
admin_email=$(field email <<<"$admin")
admin_password=$(field password <<<"$admin")
caddyfile_sha256=$(sha256sum "$here/Caddyfile" | cut -d' ' -f1)

umask 077
mkdir -p "$(dirname "$env_file")"
rendered=$(mktemp "$env_file.XXXXXX")
cat > "$rendered" <<EOF
LANGFUSE_DOMAIN=$domain
AWS_REGION=$region
S3_BUCKET=$bucket
AUTH_DISABLE_SIGNUP=$auth_disable_signup
POSTGRES_PASSWORD=$postgres_password
DATABASE_URL=$database_url
CLICKHOUSE_PASSWORD=$clickhouse_password
REDIS_AUTH=$redis_auth
NEXTAUTH_SECRET=$nextauth_secret
SALT=$salt
ENCRYPTION_KEY=$encryption_key
INIT_PUBLIC_KEY=$init_public_key
INIT_SECRET_KEY=$init_secret_key
ADMIN_EMAIL=$admin_email
ADMIN_PASSWORD=$admin_password
CADDYFILE_SHA256=$caddyfile_sha256
EOF
mv "$rendered" "$env_file"

# A DuckDNS name follows the Elastic IP: without an `ip`, DuckDNS uses the address the request comes from. The operator
# creates the token's secret (docs/runbooks/langfuse-host.md); it reaches curl on stdin, never its command line. A
# failure only warns: the name most likely still points here.
if [[ $domain == *.duckdns.org ]]; then
  duckdns_url="https://www.duckdns.org/update?domains=${domain%.duckdns.org}&token="
  if duckdns_token=$(secret duckdns-token 2>/dev/null) &&
    duckdns_answer=$(curl -sS --max-time 20 -K - <<<"url = \"$duckdns_url$duckdns_token\"") &&
    [[ $duckdns_answer == OK ]]; then
    echo "Pointed $domain at this instance"
  else
    echo "Warning: could not update $domain on DuckDNS (is the secret langfuse/duckdns-token set?)" >&2
  fi
fi

# EC2 stops an instance by shutting the OS down, and systemd stops Docker. Postgres and ClickHouse need up to 60 s
# (stop_grace_period) to shut down cleanly, so Docker gets longer than systemd's default.
mkdir -p /etc/systemd/system/docker.service.d
printf '[Service]\nTimeoutStopSec=120\n' > /etc/systemd/system/docker.service.d/stop-timeout.conf
systemctl daemon-reload

echo "Pulling the pinned images"
"${compose[@]}" pull --quiet
echo "Starting Langfuse"
"${compose[@]}" up -d --remove-orphans --wait --wait-timeout 900
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Langfuse is up at https://$domain"
