# On-premise monitoring and patching (#152)

The team learns when the on-premise product is down, and the VM keeps itself patched (PRD §9.12, ADR 0012). All of it is in the Host stack (`infra/smart_tutor_infra/stacks/host.py`) and deploys with it (`on-premise-deploy.md` §2). For deploys, the VM's layout, and Session Manager, see `on-premise-deploy.md`.

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

Every alarm emails the SNS topic **`smart-tutor-on-premise-prod-alerts`**. Its recipients are the budget's, the context `smart-tutor:budget-alert-emails` in `infra/cdk.json`, so native-cloud's budget, on-premise's budget, and these alarms all reach the same people. The same topic carries the backup alarms (a failed snapshot or nightly dump), which `on-premise-backups.md` covers. One confirmation covers both.

**After the first deploy of the Host stack, and after adding a recipient, each recipient confirms the subscription.** AWS sends an email titled "AWS Notification - Subscription Confirmation", and nothing reaches an address until its owner chooses **Confirm subscription**. To check:

```powershell
$Topic = aws sns list-topics --query "Topics[?ends_with(TopicArn, ':smart-tutor-on-premise-prod-alerts')].TopicArn" --output text
aws sns list-subscriptions-by-topic --topic-arn $Topic --query "Subscriptions[].[Endpoint, SubscriptionArn]" --output table
```

`PendingConfirmation` means the email hasn't been confirmed yet. To change the recipients, edit `smart-tutor:budget-alert-emails` and deploy the stacks; removed addresses are unsubscribed.

## The alarms

| Email | What fired | Section |
|---|---|---|
| ALARM: `smart-tutor-on-premise-prod-recover` | The EC2 **system status check** failed for 2 minutes. AWS is recovering the instance. | [Recovery](#recovery-alarm) |
| ALARM: `smart-tutor-on-premise-prod-uptime` | `https://<domain>/api/healthz` failed for 3 minutes, measured by Route 53 from several regions. | [Uptime](#uptime-alarm) |
| "The patching window smart-tutor-on-premise-prod-patching ended FAILED" (or `TIMED_OUT`) | The weekly patching, or the health check after it, failed. | [Patching](#patching-failed) |
| AWS Budgets: `smart-tutor-on-premise-prod-monthly` | Actual spend passed 80% of the monthly budget, or the forecast passed 100%. | [Budget](#budget-alert) |

The two CloudWatch alarms also email **OK** when they clear. An OK soon after an ALARM, with no action needed, is the usual end of a short outage.

### Recovery alarm

**What happened.** AWS saw a hardware or network problem on the host under the VM. The alarm's action recovers the instance: AWS moves it to healthy hardware. The instance keeps its id, Elastic IP, private address, and EBS volumes, including the data volume. Recovery reboots the VM, then Docker starts every service again (`restart: unless-stopped`, after `/data` is mounted). Expect about 5 to 10 minutes of downtime, so the uptime alarm usually fires too.

**What to do.**

1. Wait for the OK email from `-recover`, and then from `-uptime`. If both clear, nothing else is needed.
2. If the recovery alarm stays in ALARM for more than 30 minutes, check the instance:

   ```powershell
   aws ec2 describe-instance-status --instance-ids $InstanceId --include-all-instances `
       --query "InstanceStatuses[0].{State: InstanceState.Name, System: SystemStatus.Status, Instance: InstanceStatus.Status}"
   ```

   If recovery failed (AWS also emails the account about it), stop and start the instance. That moves it to new hardware too, and the Elastic IP and data volume stay:

   ```powershell
   aws ec2 stop-instances --instance-ids $InstanceId; aws ec2 wait instance-stopped --instance-ids $InstanceId
   aws ec2 start-instances --instance-ids $InstanceId; aws ec2 wait instance-status-ok --instance-ids $InstanceId
   ```

3. If the services aren't healthy afterwards, see [Bring the services back](#bring-the-services-back).

An **instance** status check failure (the VM's own OS, such as memory exhaustion or a full disk) doesn't trigger this alarm. It shows up as the uptime alarm.

### Uptime alarm

**What happened.** Route 53 health checkers in several regions request `https://<domain>/api/healthz` every 30 seconds, and the check failed for 3 minutes. The request goes through DNS, Caddy, and the API, as a learner's does. So the alarm fires when the VM is down, Caddy or the API is down, or the domain stops resolving to the Elastic IP (DuckDNS, #154). It doesn't catch a bad certificate: Route 53 doesn't validate certificates. If learners see a certificate warning, check `dc logs caddy` (`on-premise-deploy.md`, Troubleshooting). A deploy restarts the API for a few seconds, which is too short to fire it. A deploy that fails half-way can fire it.

**What to do.**

1. Open `$Url` and run the smoke test to see what fails:

   ```powershell
   python deploy/pilot/smoke_test.py $Url
   ```

2. Check that a deploy isn't running or failed: in the Systems Manager console, **Run Command → Command history**, look for `smart-tutor-on-premise-deploy`. A failed deploy stops before or during `docker compose up`, so redeploy the last good tag (`on-premise-deploy.md` §4).
3. Check the instance (the `describe-instance-status` command above). If it is stopped, start it. If its **instance** status check failed, reboot it: `aws ec2 reboot-instances --instance-ids $InstanceId`.
4. If the instance is running, [bring the services back](#bring-the-services-back) and read the logs of the unhealthy service.
5. If the services are healthy but the check still fails, check DNS: `Resolve-DnsName smart-tutor.duckdns.org` must return the Elastic IP. If it does not, run a deploy (it points the name at the instance) or update the address on duckdns.org (`on-premise-deploy.md` section 9).

### Patching failed

**What happened.** The maintenance window **`smart-tutor-on-premise-prod-patching`** failed or ran out of time. See [Weekly patching](#weekly-patching) for what it runs. Either the patching failed, so the VM may be missing security updates, or the health check after it found a service that didn't come back.

**What to do.**

1. Find the failed task. In the Systems Manager console, open **Maintenance Windows → smart-tutor-on-premise-prod-patching → History**, open the execution, then each task's output. From the shell:

   ```powershell
   $Window = aws ssm describe-maintenance-windows --filters "Key=Name,Values=smart-tutor-on-premise-prod-patching" --query "WindowIdentities[0].WindowId" --output text
   aws ssm describe-maintenance-window-executions --window-id $Window --max-results 3 --query "WindowExecutions[].[WindowExecutionId, Status, StartTime]" --output table
   ```

2. If **`HealthTask`** failed, the product may be down: [bring the services back](#bring-the-services-back) now. The uptime alarm fires too if the API is down.
3. If **`PatchTask`** failed, the output names the package or repository problem. Fix it, then patch now instead of waiting a week:

   ```powershell
   $Command = aws ssm send-command --document-name AWS-RunPatchBaseline --instance-ids $InstanceId `
       --parameters "Operation=Install,RebootOption=RebootIfNeeded" --query Command.CommandId --output text
   ```

   When it has finished (and the VM has rebooted, if it needed to), run the health check by hand (see below).

### Budget alert

**What happened.** Spend this month passed 80% of `smart-tutor:budget-monthly-usd`, or AWS forecasts it will pass 100%. The usual causes are Bedrock use, a VM larger than `t3.large`, or the native-cloud stacks running beside on-premise.

**What to do.** In **Billing → Cost Explorer**, group this month's cost by service. Check Bedrock usage in LangSmith traces, and check that no native-cloud stack (`SmartTutor-prod-*`) is running when it shouldn't be. Tell the product owner if the budget is too low for the pilot. The amount is `smart-tutor:budget-monthly-usd` in `infra/cdk.json`.

## Weekly patching

| What | Value |
|---|---|
| When | Every **Sunday at 04:00 Asia/Ho_Chi_Minh** (the app time zone, an hour after the nightly dump starts), for at most 3 hours; no task starts in the last hour |
| Window | `smart-tutor-on-premise-prod-patching`, targeting the Host instance by id |
| Patches | The baseline `smart-tutor-on-premise-prod-security`: Amazon Linux 2023 updates classified **Security**, every severity, approved as soon as they are released. The instance's `PatchGroup` tag selects it. Patch Manager reads the latest AL2023 repository, not the one the image pinned. |
| Task 1, `PatchTask` | `AWS-RunPatchBaseline` with `Install` and `RebootIfNeeded`. It reboots only when an installed patch needs it (a kernel, for example). |
| Task 2, `HealthTask` | `bash /opt/smart-tutor/on-premise/ensure-healthy.sh`: starts Docker and any service that isn't running, with the last deploy's images and settings, and waits up to 15 minutes until every service is healthy. Then it re-runs the worker's isolation and egress checks, as a deploy does (`check-worker.sh`), and fails the window (an email) if they fail. It runs even if task 1 failed. |
| On failure | An email to the alarm topic (EventBridge rule on the window's `FAILED` or `TIMED_OUT` state) |

A reboot takes the product down for a few minutes, which the uptime alarm tolerates. Patching doesn't touch our images: they change only with a deploy. A **deploy that replaces the instance** (when CDK reads a newer Amazon Linux 2023 image) also brings the operating system up to date.

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

## Bring the services back

`ensure-healthy.sh` is safe to run at any time. It changes nothing that is running and healthy, except that it stops a worker that fails its isolation or egress check:

```powershell
$Command = aws ssm send-command --document-name AWS-RunShellScript --instance-ids $InstanceId `
    --parameters 'commands=["bash /opt/smart-tutor/on-premise/ensure-healthy.sh"]' --query Command.CommandId --output text
aws ssm wait command-executed --command-id $Command --instance-id $InstanceId
aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

The output lists each service's status. If one stays unhealthy, open a shell (`on-premise-deploy.md` §7) and read its logs with `dc logs --tail 200 <service>`. Common causes: `/data` not mounted (the data volume), the disk full (`df -h / /data`; `docker image prune -af` frees old images), or Keycloak slow to start after a reboot. If a deploy left the services broken, redeploy the last good tag.

## Test the alarms

Do this once after the first deploy of the Host stack, and after changing the recipients:

```powershell
aws cloudwatch set-alarm-state --alarm-name smart-tutor-on-premise-prod-uptime --state-value ALARM `
    --state-reason "Testing the email (docs/runbooks/on-premise-monitoring.md)"
```

Each recipient gets an ALARM email. The alarm returns to its real state within a few minutes and sends an OK email. Don't test the **recovery** alarm this way: setting its state by hand also runs its recover action. It shares the topic, so the uptime test proves its emails arrive too.
