# Langfuse host (ADR 0021)

A self-hosted Langfuse v4 on its own EC2 VM, shared by any app. Code: `platform/langfuse` (stack `Langfuse-Host`, Compose bundle in `deploy/`).

Commands are for **PowerShell 7** with AWS credentials for the account (`on-premise-deploy.md` §1) and:

```powershell
function Get-LangfuseOutput($Key) {
    aws cloudformation describe-stacks --stack-name Langfuse-Host `
        --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
```

## 1. First deploy

1. Optional, a DuckDNS name: create one on duckdns.org (for example `<team>-langfuse`), set `langfuse:domain` in `platform/langfuse/cdk.json` to `<name>.duckdns.org`, and store your DuckDNS account token after step 2: `aws secretsmanager create-secret --name langfuse/duckdns-token --secret-string <token>`. Without a domain, the URL is `https://<Elastic IP>.sslip.io`.
2. Deploy the stack:

   ```powershell
   Push-Location platform/langfuse
   uv sync
   npx aws-cdk@latest diff
   npx aws-cdk@latest deploy --require-approval broadening
   Pop-Location
   $InstanceId = Get-LangfuseOutput InstanceId; $Url = Get-LangfuseOutput PublicUrl
   ```

3. Wait until SSM lists the instance `Online` (2–3 minutes): `aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$InstanceId" --query "InstanceInformationList[0].PingStatus" --output text`.
4. Run the deploy document (section 3). The first start takes a few minutes while Langfuse migrates its databases.
5. Sign in at `$Url` as the admin: `aws secretsmanager get-secret-value --secret-id langfuse/admin --query SecretString --output text` (email and password; don't paste them anywhere else). Change the password in the UI if you like; the secret is only read for the first start.
6. Confirm the `langfuse-alerts` subscription: AWS emails each address in `langfuse:alert-emails` (`platform/langfuse/cdk.json`) after the first deploy; open the email and choose **Confirm subscription**. Until then the patching window's failure email isn't delivered.

## 2. Add a person

Sign-up is off. In Langfuse, invite the person (organization **Platform** → Members). Then let them create their account:

```powershell
aws ssm put-parameter --name /langfuse/host/allow-signup --value true --overwrite
# Run the deploy document (section 3); the person signs up with the invited email.
aws ssm put-parameter --name /langfuse/host/allow-signup --value false --overwrite
# Run the deploy document again.
```

A `cdk deploy` does not change it: CloudFormation compares templates, not live values, so a hand-set `true` survives every deploy. Only the `put-parameter ... false` and a deploy-document run close sign-up again.

## 3. Deploy or upgrade

`cdk deploy` uploads `platform/langfuse/deploy/` as a bundle; the document copies it to the VM and runs `deploy.sh`:

```powershell
$Command = aws ssm send-command --document-name langfuse-deploy --instance-ids $InstanceId --query Command.CommandId --output text
do { Start-Sleep -Seconds 15; $Status = aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query Status --output text } while ($Status -in 'Pending', 'InProgress', 'Delayed')
aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

Don't send the document again while one is running: two `deploy.sh` runs would race. The first run takes several minutes (image pulls, migrations), which is why this loops instead of using `aws ssm wait command-executed`, which gives up after about 100 seconds.

After every `cdk deploy`, re-read `$InstanceId = Get-LangfuseOutput InstanceId`, wait until SSM lists it `Online` (section 1, step 3), then run the document. The AMI is the latest Amazon Linux 2023, resolved on every deploy, so a deploy after Amazon publishes a new one replaces the instance: it gets a new id and Langfuse is down until the document runs.

To upgrade Langfuse, change the two `langfuse/*:4.x.y` tags in `deploy/compose.yaml` (read Langfuse's release notes first; both must match), run the tests, `cdk deploy`, then run the document.

Deploy between 07:00 and 17:30, or start the host first (section 4): the 18:00 stop cuts off a deploy that is still running.

After the `cdk deploy` that added the hours and patching, run the deploy document once: the patching window's health check needs `ensure-healthy.sh` on the VM, and until the document has copied it the window fails with "ensure-healthy.sh is missing: run the deploy document".

Stopping and starting the instance needs no deploy: every service has `restart: unless-stopped`.

## 4. Hours, starting by hand

| Local time (Asia/Ho_Chi_Minh) | Schedule | What it does |
|---|---|---|
| 18:00 | `stop` | Stops the instance |
| 00:00 | `stop-late` | Stops it again, in case someone started it in the evening |
| 07:00 | `start` | Starts it; Docker brings every service back within a few minutes |

The schedules are in the group `langfuse-off-hours`. A stop shuts the OS down: ClickHouse and Postgres get 60 s and Docker 120 s to stop. Outside the hours Langfuse doesn't answer, so apps must not depend on it being up. Neither host needs the other: Langfuse runs with the app host stopped, and the app host with Langfuse stopped.

**Start the host by hand** (any hour; it runs until the next `stop` or `stop-late`):

```powershell
aws ec2 start-instances --instance-ids $InstanceId
aws ec2 wait instance-running --instance-ids $InstanceId
# A few minutes later, open $Url.
```

Nothing else is needed: the data volume mounts, every service has `restart: unless-stopped`, and the Elastic IP, DuckDNS name, and certificates stay.

**Keep it up past midnight:** disable `stop-late`, then enable it again the next morning. `update-schedule` replaces the whole schedule, so read it first and send it back with the new state:

```powershell
$Group = "langfuse-off-hours"
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

## 5. Patching and health

| What | Value |
|---|---|
| When | Every **Sunday at 07:20 Asia/Ho_Chi_Minh**, twenty minutes after the 07:00 start, for at most 3 hours; no task starts in the last hour |
| Window | `langfuse-patching`, targeting the instance |
| Patches | The baseline `langfuse-security`: Amazon Linux 2023 updates classified **Security**. The instance's `PatchGroup` tag (`langfuse`) selects it. |
| Task 1, `PatchTask` | `AWS-RunPatchBaseline` with `Install` and `RebootIfNeeded`. It reboots only when an installed patch needs it (a kernel, for example). |
| Task 2, `HealthTask` | `bash /opt/langfuse/ensure-healthy.sh`: starts Docker and any service that isn't running, with the last deploy's settings, and waits up to 15 minutes until every service is healthy. It never pulls images. If the file is missing it fails with "ensure-healthy.sh is missing: run the deploy document". |
| On failure | An email to the `langfuse-alerts` topic (EventBridge rule on the window's `FAILED` or `TIMED_OUT` state) |

A reboot takes Langfuse down for a few minutes. Patching doesn't touch the Langfuse images: they change only with a deploy.

To see what is installed or missing:

```powershell
aws ssm describe-instance-patch-states --instance-ids $InstanceId `
    --query "InstancePatchStates[0].{Installed: InstalledCount, Missing: MissingCount, Failed: FailedCount, RebootPending: InstalledPendingRebootCount, Last: OperationEndTime}"
```

To move the window, change `PATCH_SCHEDULE` in `platform/langfuse/langfuse_platform/host_stack.py` (a cron expression in Asia/Ho_Chi_Minh) and `cdk deploy`. To pause patching, disable the window in the console (**Maintenance Windows → Edit → Enabled**), and enable it again afterwards.

**Bring the services back by hand** (after a failed window, or when `$Url` doesn't answer while the host runs). Poll it like section 3:

```powershell
$Command = aws ssm send-command --document-name AWS-RunShellScript --instance-ids $InstanceId `
    --parameters 'commands=["bash /opt/langfuse/ensure-healthy.sh"]' --query Command.CommandId --output text
do { Start-Sleep -Seconds 15; $Status = aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query Status --output text } while ($Status -in 'Pending', 'InProgress', 'Delayed')
aws ssm get-command-invocation --command-id $Command --instance-id $InstanceId --query "{Status: Status, Output: StandardOutputContent, Errors: StandardErrorContent}"
```

No alarm watches Langfuse (ADR 0022): open `$Url` when in doubt. A failed patching window emails the addresses in `langfuse:alert-emails` (`platform/langfuse/cdk.json`); each address confirms the SNS subscription email once.

## 6. Restore from a snapshot

Snapshots of the data volume are taken daily at 02:00 Asia/Ho_Chi_Minh (19:00 UTC) and kept 7 days (**EC2 → Snapshots**; the volume carries the tag `langfuse:snapshots` = `langfuse`, which the snapshot policy targets). To restore: set `langfuse:data-snapshot-id` in `cdk.json` to the snapshot id and `cdk deploy`. That creates a volume from the snapshot and replaces the instance, whose first boot attaches it; then re-read `$InstanceId`, wait until SSM lists it `Online` (section 1, step 3), and run the deploy document (the replaced instance is new, and Langfuse is down until it runs). Leave `langfuse:data-snapshot-id` set afterwards: clearing it swaps in a blank volume (its final snapshot keeps the data) and Langfuse starts empty. Keep the secrets: `encryption-seed` in particular must be the one the data was written with. A restore in a live stack keeps them.

## 7. Tear down

`npx aws-cdk@latest destroy Langfuse-Host` (from `platform/langfuse`). The data volume leaves a final snapshot, and the bucket is kept (delete it by hand when sure). Its name is fixed (`langfuse-<account>-<region>`), so a later deploy fails with "already exists" until you empty and delete the bucket.

`destroy` also schedules the `langfuse/*` secrets for deletion. The final snapshot can only be used with the same secrets (`encryption-seed` and the database passwords), so treat a destroy as deleting the data unless you recover the secrets first: within their recovery window (30 days, the Secrets Manager default; the stack sets none), run `aws secretsmanager restore-secret --secret-id langfuse/<name>` for each one. While a secret is scheduled for deletion, or after you restore it, a new stack can't create a secret with the same name.
