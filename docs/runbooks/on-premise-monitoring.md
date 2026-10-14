# On-premise hours, monitoring, and patching (#152, ADR 0022)

The host runs 07:00–18:00 Asia/Ho_Chi_Minh and patches itself weekly (PRD §9.12, ADR 0012, ADR 0022). There are no CloudWatch alarms: nobody is emailed when the product is down, so check it by hand when in doubt. All of it is in the Host stack (`infra/smart_tutor_infra/stacks/host.py`) and deploys with it (`on-premise-deploy.md` §2). For deploys, the VM's layout, and Session Manager, see `on-premise-deploy.md`.

Commands are for **PowerShell 7**, with the shell set up as in `on-premise-deploy.md` §1 and these names:

```powershell
function Get-Output($Key) {
    aws cloudformation describe-stacks --stack-name SmartTutor-OnPremise-prod-Host `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
$InstanceId = Get-Output InstanceId
$Url = Get-Output PublicUrl
```

**After deploying the Host stack with these changes, redeploy the current tag** (`on-premise-deploy.md` §4). `cdk deploy` uploads the bundle, but only a deploy copies it to the VM, and the patching window's health check needs `ensure-healthy.sh` from it. Until then, the window fails with "ensure-healthy.sh is missing".

## Who gets the emails

The SNS topic **`smart-tutor-on-premise-prod-alerts`** emails the budget's recipients (`smart-tutor:budget-alert-emails` in `infra/cdk.json`) when the weekly patching fails. It is the only email the Host stack sends.

**After the first deploy of the Host stack, and after adding a recipient, each recipient confirms the subscription.** AWS sends an email titled "AWS Notification - Subscription Confirmation", and nothing reaches an address until its owner chooses **Confirm subscription**. To check:

```powershell
$Topic = aws sns list-topics --query "Topics[?ends_with(TopicArn, ':smart-tutor-on-premise-prod-alerts')].TopicArn" --output text
aws sns list-subscriptions-by-topic --topic-arn $Topic --query "Subscriptions[].[Endpoint, SubscriptionArn]" --output table
```

`PendingConfirmation` means the email hasn't been confirmed yet. To change the recipients, edit `smart-tutor:budget-alert-emails` and deploy the stacks; removed addresses are unsubscribed.

## Emails

| Email | What happened | Section |
|---|---|---|
| "The patching window smart-tutor-on-premise-prod-patching ended FAILED" (or `TIMED_OUT`) | The weekly patching, or the health check after it, failed. | [Patching](#patching-failed) |
| AWS Budgets: `smart-tutor-on-premise-prod-monthly` | Actual spend passed 80% of the monthly budget, or the forecast passed 100%. | [Budget](#budget-alert) |

### Patching failed

**What happened.** The maintenance window **`smart-tutor-on-premise-prod-patching`** failed or ran out of time. See [Weekly patching](#weekly-patching) for what it runs. Either the patching failed, so the VM may be missing security updates, or the health check after it found a service that didn't come back.

**What to do.**

1. Find the failed task. In the Systems Manager console, open **Maintenance Windows → smart-tutor-on-premise-prod-patching → History**, open the execution, then each task's output. From the shell:

   ```powershell
   $Window = aws ssm describe-maintenance-windows --filters "Key=Name,Values=smart-tutor-on-premise-prod-patching" --query "WindowIdentities[0].WindowId" --output text
   aws ssm describe-maintenance-window-executions --window-id $Window --max-results 3 --query "WindowExecutions[].[WindowExecutionId, Status, StartTime]" --output table
   ```

2. If **`HealthTask`** failed, the product may be down: [bring the services back](#bring-the-services-back) now.
3. If **`PatchTask`** failed, the output names the package or repository problem. Fix it, then patch now instead of waiting a week:

   ```powershell
   $Command = aws ssm send-command --document-name AWS-RunPatchBaseline --instance-ids $InstanceId `
       --parameters "Operation=Install,RebootOption=RebootIfNeeded" --query Command.CommandId --output text
   ```

   When it has finished (and the VM has rebooted, if it needed to), run the health check by hand (see below).

### Budget alert

**What happened.** Spend this month passed 80% of `smart-tutor:budget-monthly-usd`, or AWS forecasts it will pass 100%. The usual causes are Bedrock use, a VM larger than `t3.large`, or the native-cloud stacks running beside on-premise.

**What to do.** In **Billing → Cost Explorer**, group this month's cost by service. Check Bedrock usage in Phoenix traces (LLM spans' token counts), and check that no native-cloud stack (`SmartTutor-prod-*`) is running when it shouldn't be. Tell the product owner if the budget is too low for the pilot. The amount is `smart-tutor:budget-monthly-usd` in `infra/cdk.json`.

## Hours (ADR 0022)

| Local time (Asia/Ho_Chi_Minh) | Schedule | What it does |
|---|---|---|
| 18:00 | `stop` | Stops the instance |
| 00:00 | `stop-late` | Stops it again, in case someone started it in the evening |
| 07:00 | `start` | Starts it; Docker brings every service back within a few minutes |

The schedules are in the group `smart-tutor-on-premise-prod-off-hours`. A stop shuts the OS down: Postgres gets 60 s and Docker 120 s to stop. Outside the hours the site doesn't answer.

**Start the host by hand** (any hour; it runs until the next `stop` or `stop-late`):

```powershell
aws ec2 start-instances --instance-ids $InstanceId
aws ec2 wait instance-running --instance-ids $InstanceId
# A few minutes later:
Invoke-WebRequest "$Url/api/healthz" -UseBasicParsing | Select-Object StatusCode
```

Nothing else is needed: the data volume mounts, Docker starts every service, and the Elastic IP, DuckDNS name, and certificates stay. Uploads queued overnight are processed, and a nightly dump that was missed runs.

**Keep it up past midnight:** disable `stop-late`, then enable it again the next morning. `update-schedule` replaces the whole schedule, so read it first and send it back with the new state:

```powershell
$Group = "smart-tutor-on-premise-prod-off-hours"
$s = aws scheduler get-schedule --group-name $Group --name stop-late | ConvertFrom-Json
$Target = Join-Path $env:TEMP stop-late-target.json     # files, not inline JSON
$Window = Join-Path $env:TEMP stop-late-window.json
$s.Target | ConvertTo-Json -Depth 5 | Set-Content -Encoding utf8NoBOM $Target
$s.FlexibleTimeWindow | ConvertTo-Json | Set-Content -Encoding utf8NoBOM $Window
aws scheduler update-schedule --group-name $Group --name stop-late --state DISABLED --description $s.Description `
    --schedule-expression $s.ScheduleExpression --schedule-expression-timezone $s.ScheduleExpressionTimezone `
    --flexible-time-window file://$Window --target file://$Target
```

Next morning, run the same commands with `--state ENABLED`.

**Stop it now:** `aws ec2 stop-instances --instance-ids $InstanceId`.

**Did a schedule run?** `StateTransitionReason` shows the last stop or start only: `aws ec2 describe-instances --instance-ids $InstanceId --query "Reservations[0].Instances[0].[State.Name, StateTransitionReason]"`. For the history, ask CloudTrail: `aws cloudtrail lookup-events --lookup-attributes AttributeKey=ResourceName,AttributeValue=$InstanceId --query "Events[?EventName=='StopInstances' || EventName=='StartInstances'].[EventTime,EventName,Username]" --output table`. In CloudWatch, the free `AWS/Scheduler` metrics `InvocationAttemptCount` and `TargetErrorCount` (dimension `ScheduleGroup`) show attempts and failures.

**Is the product up?** No alarm watches it. Open `$Url`, or `Invoke-WebRequest "$Url/api/healthz"`. If the host is running but the site isn't, [bring the services back](#bring-the-services-back). If AWS reports a hardware problem, EC2's default automatic recovery moves the instance to healthy hardware without an email; the instance keeps its id, address, and volumes.

## Weekly patching

| What | Value |
|---|---|
| When | Every **Sunday at 07:20 Asia/Ho_Chi_Minh**, twenty minutes after the 07:00 start, for at most 3 hours; no task starts in the last hour |
| Window | `smart-tutor-on-premise-prod-patching`, targeting the Host instance by id |
| Patches | The baseline `smart-tutor-on-premise-prod-security`: Amazon Linux 2023 updates classified **Security**, every severity, approved as soon as they are released. The instance's `PatchGroup` tag selects it. Patch Manager reads the latest AL2023 repository, not the one the image pinned. |
| Task 1, `PatchTask` | `AWS-RunPatchBaseline` with `Install` and `RebootIfNeeded`. It reboots only when an installed patch needs it (a kernel, for example). |
| Task 2, `HealthTask` | `bash /opt/smart-tutor/on-premise/ensure-healthy.sh`: starts Docker and any service that isn't running, with the last deploy's images and settings, and waits up to 15 minutes until every service is healthy. Then it re-runs the worker's isolation and egress checks, as a deploy does (`check-worker.sh`), and fails the window (an email) if they fail. It runs even if task 1 failed. |
| On failure | An email to the alert topic (EventBridge rule on the window's `FAILED` or `TIMED_OUT` state) |

A reboot takes the product down for a few minutes. Patching doesn't touch our images: they change only with a deploy. A **deploy that replaces the instance** (when CDK reads a newer Amazon Linux 2023 image) also brings the operating system up to date.

To see what is installed or missing:

```powershell
aws ssm describe-instance-patch-states --instance-ids $InstanceId `
    --query "InstancePatchStates[0].{Installed: InstalledCount, Missing: MissingCount, Failed: FailedCount, RebootPending: InstalledPendingRebootCount, Last: OperationEndTime}"
```

To move the window, change `PATCH_SCHEDULE` in `host.py` (a cron expression in the app time zone) and deploy the stacks. To pause patching, disable the window in the console (**Maintenance Windows → Edit → Enabled**), and enable it again afterwards.

## Citation highlight misses

**What it counts.** Each time the document viewer opens a cited page and shows "Couldn't highlight the passage on this page." The count is one number per UTC day in the table `highlight_misses`: no user, chunk, document, or text (PRD §9.4, §10.1). It sends no email.

**How to read it.** Open a shell (`on-premise-deploy.md` §7), define `dc` as there, and run:

```bash
dc exec postgres psql -U postgres -d smart_tutor -c "SELECT day, misses FROM highlight_misses ORDER BY day DESC LIMIT 30;"
```

A day with no row had no misses. A few a day is normal: a passage that spans a page break, or a PDF whose text differs from what the worker extracted.

**What to do when it climbs.** Check recent uploads' chunks for a null `start_index` (the worker sets it at ingestion and backfills it at startup; a chunk it can't locate stays null):

```bash
dc exec postgres psql -U postgres -d smart_tutor -c "SELECT count(*) FILTER (WHERE start_index IS NULL) AS missing, count(*) AS total FROM chunks;"
```

If the nulls are recent, the ingestion's chunking changed or the worker failed to backfill: read `dc logs worker` (it runs the backfill at startup and logs each chunk it can't place). If `start_index` is set and the count still climbs, compare the viewer's matcher with the seed-corpus test in `web/src/features/viewer/passage.seed.test.ts` and add the failing PDF to it.

## Question screen failures

**What it counts.** The optional question screen (PRD D30, `on-premise-deploy.md` section 12) calls Bedrock Guardrails, or runs DetectJailbreak in the agent (`guardrails_ai`), before search. When that call fails or takes longer than 1 second, the question goes on unscreened and the agent adds one to the CloudWatch metric **`QuestionScreenFailures`** (namespace `SmartTutor/Agent`, dimension `Deployment` = `on-premise`). The metric is a bare count: no user, question, or error text. It sends no email. While the screen is `off` (the default) nothing is called and the count stays empty.

**How to read it.** In the CloudWatch console open **Metrics → All metrics → SmartTutor/Agent → Deployment**, and graph `QuestionScreenFailures` with the statistic **Sum** over 5 minutes. From the shell:

```powershell
aws cloudwatch get-metric-statistics --namespace SmartTutor/Agent --metric-name QuestionScreenFailures `
    --dimensions Name=Deployment,Value=on-premise --start-time (Get-Date).AddDays(-1).ToUniversalTime().ToString("o") `
    --end-time (Get-Date).ToUniversalTime().ToString("o") --period 3600 --statistics Sum `
    --query "sort_by(Datapoints,&Timestamp)[].[Timestamp, Sum]" --output table
```

No data points means no failures (or the screen is off). The first question after an agent restart may count one failure: the TLS handshake and credential fetch can exceed the 1 second timeout. A failure is not an outage: the code checks and the output guard still apply, and the turn is answered.

**What to do when it climbs.**

1. Compare it with the turns asked. A few a day is noise. A steady share means learners are asking unscreened questions.
2. Read the agent's log for the cause (`dc logs --tail 200 agent` in a shell, `on-premise-deploy.md` section 7): each failure logs `question screen unavailable, letting the question through` and the exception's type only. `TimeoutError` means Bedrock Guardrails was slower than 1 second (a latency regression, or a cold cross-region route). `ClientError` types such as access denied, validation, or throttling point at the agent's IAM (`bedrock:ApplyGuardrail` on the guardrail and the `us.guardrail.v1:0` profile), a guardrail version that no longer exists, or the guardrail's quota. With the local screen (`guardrails_ai`), turn latency that rises by about 1 second and stays there while the count rises can mean a stuck model thread: one hung run holds the screen, so every later question waits out the 1 second and goes on unscreened; restart the agent.
3. If the cause is not fixed quickly and the unscreened share matters, turn the screen off (`on-premise-deploy.md` section 12). A missing `cloudwatch:PutMetricData` grant on the agent shows as `could not count QuestionScreenFailures` warnings in the agent's log (the turn is not affected); no data points alone means no failures.

## Bring the services back

`ensure-healthy.sh` is safe to run at any time. It changes nothing that is running and healthy, except that it stops a worker that fails its isolation or egress check:

```powershell
$Command = aws ssm send-command --document-name AWS-RunShellScript --instance-ids $InstanceId `
    --parameters 'commands=["bash /opt/smart-tutor/on-premise/ensure-healthy.sh"]' --query Command.CommandId --output text
aws ssm wait command-executed --command-id $Command --instance-id $InstanceId
aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

The output lists each service's status. If one stays unhealthy, open a shell (`on-premise-deploy.md` §7) and read its logs with `dc logs --tail 200 <service>`. Common causes: `/data` not mounted (the data volume), the disk full (`df -h / /data`; `docker image prune -af` frees old images), or Keycloak slow to start after a reboot. If a deploy left the services broken, redeploy the last good tag.

## Phoenix's memory and database size (#288)

Phoenix itself is capped at 1 GB (`mem_limit`; it idles at about 450 MiB) and is restarted if it goes over. ADR 0017's estimate of 1 to 2 GB includes the database's growth in Postgres, which has no limit. Container limits now total about 5.75 GiB of the t3.large's ~7.6 GiB, with Postgres and Caddy unlimited and no swap, so watch available memory. Check monthly, and after a traffic jump. From a Session Manager shell (`on-premise-deploy.md` §7):

```bash
free -m
docker stats --no-stream
df -h /data
dc exec postgres psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('phoenix'));"
```

When it grows, lower `trace-sampling-rate` (`on-premise-deploy.md` §10) or shorten retention in Phoenix's *Settings, Data Retention*, never above 180 days. If the host's available memory stays under about 1 GB, move to a larger instance (`smart-tutor:on-premise-instance-type`).
