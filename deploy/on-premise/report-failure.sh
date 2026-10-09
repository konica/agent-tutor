#!/usr/bin/env bash
# Reports that a scheduled job failed (#151): smart-tutor-job-failed@<job>.service runs it through the job's
# OnFailure=. The Host stack alarms on SmartTutor/OnPremise JobFailed for each job and emails the alert addresses.
#   report-failure.sh smart-tutor-backup
set -euo pipefail

job=${1:?usage: report-failure.sh <job, the unit name without .service>}
region=$(sed -n 's/^AWS_REGION=//p' /etc/smart-tutor/smart-tutor.env)

aws cloudwatch put-metric-data --region "$region" \
  --namespace SmartTutor/OnPremise --metric-name JobFailed --dimensions "Job=$job" --value 1 --unit Count
echo "Reported that $job failed"
