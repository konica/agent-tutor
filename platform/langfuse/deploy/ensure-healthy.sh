#!/usr/bin/env bash
# Brings Langfuse back after the weekly patching: the maintenance window langfuse-patching (LangfuseHostStack) runs it as
# root after AWS-RunPatchBaseline, which may have rebooted the VM. Operators can run it too:
#   sudo bash /opt/langfuse/ensure-healthy.sh
# It starts Docker and any service that isn't running, with the settings of the last deploy, and waits until every
# service is healthy. It fails if one isn't healthy within 15 minutes, which fails the window and emails
# langfuse-alerts. It doesn't pull: that is deploy.sh's job. Like deploy.sh, it prints no secret.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/langfuse/langfuse.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")

if [ ! -f "$env_file" ]; then
  echo "Nothing to check: Langfuse hasn't been deployed on this VM yet"
  exit 0
fi

systemctl is-active --quiet docker || systemctl start docker
"${compose[@]}" up -d --wait --wait-timeout 900
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Every service is healthy"
