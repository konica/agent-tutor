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

Stopping and starting the instance needs no deploy: every service has `restart: unless-stopped`.

## 4. Restore from a snapshot

Snapshots of the data volume are taken daily at 02:00 Asia/Ho_Chi_Minh (19:00 UTC) and kept 7 days (**EC2 → Snapshots**; the volume carries the tag `langfuse:snapshots` = `langfuse`, which the snapshot policy targets). To restore: set `langfuse:data-snapshot-id` in `cdk.json` to the snapshot id and `cdk deploy`. That creates a volume from the snapshot and replaces the instance, whose first boot attaches it; then re-read `$InstanceId`, wait until SSM lists it `Online` (section 1, step 3), and run the deploy document (the replaced instance is new, and Langfuse is down until it runs). Leave `langfuse:data-snapshot-id` set afterwards: clearing it swaps in a blank volume (its final snapshot keeps the data) and Langfuse starts empty. Keep the secrets: `encryption-seed` in particular must be the one the data was written with. A restore in a live stack keeps them.

## 5. Tear down

`npx aws-cdk@latest destroy Langfuse-Host` (from `platform/langfuse`). The data volume leaves a final snapshot, and the bucket is kept (delete it by hand when sure). Its name is fixed (`langfuse-<account>-<region>`), so a later deploy fails with "already exists" until you empty and delete the bucket.

`destroy` also schedules the `langfuse/*` secrets for deletion. The final snapshot can only be used with the same secrets (`encryption-seed` and the database passwords), so treat a destroy as deleting the data unless you recover the secrets first: within their recovery window (30 days, the Secrets Manager default; the stack sets none), run `aws secretsmanager restore-secret --secret-id langfuse/<name>` for each one. While a secret is scheduled for deletion, or after you restore it, a new stack can't create a secret with the same name.
