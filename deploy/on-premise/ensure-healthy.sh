#!/usr/bin/env bash
# Brings the on-premise services back after the weekly patching (#152): the maintenance window <prefix>-patching
# (HostStack) runs it as root after AWS-RunPatchBaseline, which may have rebooted the VM. Operators can run it too:
#   sudo bash /opt/smart-tutor/on-premise/ensure-healthy.sh
#
# It starts Docker and any service that isn't running, with the images and settings of the last deploy, and waits until
# every service is healthy. Then it re-proves the worker's isolation and egress block, as a deploy does
# (check-worker.sh, #153), so patching never brings back a worker that a deploy stopped, and a Docker upgrade can't
# open its way out unnoticed. It fails if a service isn't healthy within 15 minutes or the worker check fails, which
# fails the maintenance window and emails the alarm recipients. It doesn't pull or migrate: that is deploy.sh's job.
# Like deploy.sh, it prints no secret.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
env_file=/etc/smart-tutor/smart-tutor.env
compose=(docker compose --project-directory "$here" -f "$here/compose.yaml" --env-file "$env_file")
# shellcheck source=check-worker.sh
source "$here/check-worker.sh"

if [ ! -f "$env_file" ]; then
  echo "Nothing to check: Smart Tutor hasn't been deployed on this VM yet"
  exit 0
fi

systemctl is-active --quiet docker || systemctl start docker
# The same tag again: Compose recreates nothing that runs, and starts what doesn't.
"${compose[@]}" up -d --wait --wait-timeout 900
check_worker || exit 1
"${compose[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
echo "Every service is healthy"
