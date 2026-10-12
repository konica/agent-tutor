<#
.SYNOPSIS
    Tears down the native-cloud pilot (SmartTutor-prod-*) to stop paying for EKS, RDS, NAT, the ALB and CloudFront (#177).
    See pilot-teardown.md.

.DESCRIPTION
    1. Preflight: checks the tools, the caller and the repository variables NATIVE_CLOUD_AUTO_DEPLOY and PRODUCTION_DEPLOY
       (a merge must not redeploy native-cloud, which needs both to be `true`; NATIVE_CLOUD_AUTO_DEPLOY must not be
       `true`, or the next merge to main redeploys the pilot), and lists the stacks it will delete and keep.
    2. Asks you to type the account id (skipped with -Force and in -DryRun).
    3. Removes what Kubernetes created outside CloudFormation (the smart-tutor release, TargetGroupBindings, the
       add-ons), so no security-group rules or ENIs block the Edge and Network deletes.
    4. cdk destroy, one stack at a time: Storage, Edge, Data, Cluster, Config, Registry, Budgets (only with
       -DeleteBudget), Network. Before Network it clears the leaked VPC-CNI ENIs and CloudFront's VPC-origin security group.
    5. Reports what is left (RDS final snapshot, documents bucket, log groups, secrets), deletes it only when you
       pass -DeleteDatabaseSnapshots, -DeleteDocumentsBucket or -DeleteLogGroups (irreversible; each asks for its
       own confirmation unless -Force), and checks that no EKS cluster, ALB or NAT gateway is left.
    Kept on purpose, and the dry run says why: SmartTutor-prod-GitHubDeploy (it owns the account's GitHub OIDC provider,
    which on-premise's deploy role imports: the one resource the modes share, ADR 0016), CDKToolkit, and
    SmartTutor-prod-Budgets (free) unless -DeleteBudget. It deletes nothing of on-premise (SmartTutor-OnPremise-*,
    smart-tutor-on-premise*), which keeps running. Safe to run again after a partial failure: it skips what is gone.
    Run with -DryRun first: it only reads and prints what it would do.

.EXAMPLE
    gh variable delete NATIVE_CLOUD_AUTO_DEPLOY --repo konica/agent-tutor   # or set it to false
    ./docs/runbooks/pilot-teardown.ps1 -AwsProfile default -DryRun
    ./docs/runbooks/pilot-teardown.ps1 -AwsProfile default
    ./docs/runbooks/pilot-teardown.ps1 -AwsProfile default -DeleteLogGroups -DeleteDatabaseSnapshots -DeleteDocumentsBucket
#>
[CmdletBinding()]
param(
    # An AWS CLI profile whose principal is in smart-tutor:eks-admin-principals (infra/cdk.json).
    [string] $AwsProfile = $(if ($env:AWS_PROFILE) { $env:AWS_PROFILE } else { "default" }),
    [string] $Region = "us-east-1",
    [string] $Repo = "konica/agent-tutor",
    [switch] $DryRun,
    # Skip every confirmation prompt (for unattended runs). Irreversible switches still need to be passed.
    [switch] $Force,
    # Also delete the Budgets stack (the budget smart-tutor-prod-monthly).
    [switch] $DeleteBudget,
    # Irreversible: learner data.
    [switch] $DeleteDatabaseSnapshots,
    [switch] $DeleteDocumentsBucket,
    [switch] $DeleteLogGroups
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false   # we check $LASTEXITCODE ourselves

$RepoRoot = (Resolve-Path "$PSScriptRoot/../..").Path
$InfraDir = Join-Path $RepoRoot "infra"
$ClusterName = "smart-tutor-prod"
$CdkVersion = "2.1145.0"   # same as .github/workflows/deploy-native-cloud.yml
# In dependency order. Storage goes before Edge because it imports Edge's CloudFront URL for the bucket CORS rule.
$DeleteStacks = @("Storage", "Edge", "Data", "Cluster", "Config", "Registry") + @(if ($DeleteBudget) { "Budgets" }) + @("Network") |
    ForEach-Object { "SmartTutor-prod-$_" }
# Kept on purpose, with the reason the run prints. GitHubDeploy is the accepted exception to "the modes share no
# stack" (ADR 0016). Every name this script deletes is native-cloud's; none starts with SmartTutor-OnPremise- or
# smart-tutor-on-premise (#207).
$KeepStacks = [ordered]@{
    "SmartTutor-prod-GitHubDeploy" = "owns the account's GitHub OIDC provider, which on-premise's deploy role imports (ADR 0016)"
    "CDKToolkit"                   = "the account's CDK bootstrap, which both modes deploy with"
}
if (-not $DeleteBudget) { $KeepStacks["SmartTutor-prod-Budgets"] = "the budget smart-tutor-prod-monthly is free; -DeleteBudget deletes it" }
# The stacks create these names; CloudFormation deletes the secrets without a recovery window, but a secret that was
# scheduled for deletion before (or by hand) blocks a redeploy that recreates the name.
$SecretNames = "smart-tutor/keycloak/api-client", "smart-tutor/keycloak/admin", "smart-tutor/keycloak/mcp-client",
    "smart-tutor/rds/master", "smart-tutor/db/app", "smart-tutor/db/keycloak"
$LogGroupPrefixes = "/aws/eks/smart-tutor-prod", "/aws/rds/instance/smart-tutor-prod", "/aws/lambda/SmartTutor-prod-"

# The script runs in your PowerShell session, so save what it changes and restore it at the end (finally block).
# A terminal that loaded the repo's .env sends S3, SQS and SSM calls to LocalStack (AWS_ENDPOINT_URL_*), and
# environment access keys override any profile. Both must be off here: this script talks to real AWS only.
$SavedEnv = @{}
$Overrides = @(Get-ChildItem Env: | Where-Object Name -like "AWS_ENDPOINT_URL*" | ForEach-Object Name) +
    @("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
foreach ($Name in $Overrides + @("AWS_PROFILE", "AWS_REGION", "AWS_IGNORE_CONFIGURED_ENDPOINT_URLS",
        "JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION")) {
    $SavedEnv[$Name] = [Environment]::GetEnvironmentVariable($Name)
}
foreach ($Name in $Overrides) {
    if ($SavedEnv[$Name]) { Write-Host "Ignoring $Name from this terminal for the run" -ForegroundColor DarkGray }
    Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
}
$env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = "true"   # also skips endpoint_url settings in ~/.aws/config
$env:AWS_PROFILE = $AwsProfile
$env:AWS_REGION = $Region
$env:JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = "1"

function Invoke-Step([string] $Description, [scriptblock] $Action) {
    if ($DryRun) { Write-Host "[dry run] $Description" -ForegroundColor Yellow; return }
    Write-Host "-> $Description" -ForegroundColor Cyan
    $global:LASTEXITCODE = 0
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Description (exit code $LASTEXITCODE)" }
}

# True when the user typed the expected text. -DryRun never prompts (the step is only printed); -Force never asks.
function Confirm-Typed([string] $Question, [string] $Expected) {
    if ($DryRun -or $Force) { return $true }
    return (Read-Host "$Question Type '$Expected' to continue") -ceq $Expected
}

function Get-Json([scriptblock] $Command) {
    $Text = & $Command
    if ($LASTEXITCODE -ne 0) { throw "AWS CLI call failed (exit code $LASTEXITCODE)" }
    if ($Text) { return $Text | ConvertFrom-Json }
}

# What blocks the VPC delete after the other stacks are gone. Everything is scoped to $VpcId.
function Remove-VpcBlockers([string] $VpcId) {
    $Filters = @("Name=vpc-id,Values=$VpcId", "Name=status,Values=available",
        "Name=tag:cluster.k8s.amazonaws.com/name,Values=$ClusterName")
    # The VPC CNI can leak ENIs when nodes terminate; only the unattached ones of this cluster are removed.
    $Enis = @(Get-Json { aws ec2 describe-network-interfaces --filters $Filters --query "NetworkInterfaces[].NetworkInterfaceId" --output json })
    foreach ($Eni in $Enis) {
        Invoke-Step "Delete leaked VPC-CNI network interface $Eni in $VpcId" { aws ec2 delete-network-interface --network-interface-id $Eni }
    }
    if (-not $Enis) { Write-Host "No leaked VPC-CNI network interfaces in $VpcId" }

    # CloudFront releases its VPC-origin ENIs some time after the distribution is gone; they sit in this group and
    # block the VPC delete. The group itself is not managed by CloudFormation.
    $Sg = aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VpcId" "Name=group-name,Values=CloudFront-VPCOrigins-Service-SG" `
        --query "SecurityGroups[0].GroupId" --output text
    if ($LASTEXITCODE -ne 0) { throw "Could not look up the CloudFront VPC-origin security group" }
    if (-not $Sg -or $Sg -eq "None") { Write-Host "No CloudFront-VPCOrigins-Service-SG in $VpcId"; return }
    Invoke-Step "Wait up to 45 min until $Sg has no network interfaces, then delete it" {
        $Deadline = (Get-Date).AddMinutes(45)
        while ($true) {
            $Left = @(Get-Json { aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=$VpcId" "Name=group-id,Values=$Sg" `
                    --query "NetworkInterfaces[].NetworkInterfaceId" --output json })
            if (-not $Left) { break }
            if ((Get-Date) -gt $Deadline) { throw "$($Left.Count) network interface(s) still use $Sg after 45 min: $($Left -join ', ')" }
            Write-Host "   $($Left.Count) CloudFront network interface(s) still attached; next check in 30 s"
            Start-Sleep -Seconds 30
        }
        aws ec2 delete-security-group --group-id $Sg
    }
}

try {
    # --- Preflight -----------------------------------------------------------------------------------------------
    foreach ($Tool in "aws", "gh", "npx", "uv", "kubectl", "helm") {
        if (-not (Get-Command $Tool -ErrorAction SilentlyContinue)) { throw "'$Tool' is not on PATH." }
    }
    $AccountId = aws sts get-caller-identity --query Account --output text
    if ($LASTEXITCODE -ne 0) { throw "No AWS credentials for profile '$AwsProfile'. Sign in first." }
    $Caller = aws sts get-caller-identity --query Arn --output text
    Write-Host "AWS account $AccountId as $Caller, region $Region"

    $Context = (Get-Content (Join-Path $InfraDir "cdk.json") -Raw | ConvertFrom-Json).context
    # cdk.json lists IAM paths ("user/poweruser"); the cluster's access entries add this account.
    $AdminArns = $Context."smart-tutor:eks-admin-principals" | ForEach-Object { "arn:aws:iam::${AccountId}:$_" }
    if ($Caller -notin $AdminArns) {
        Write-Warning ("$Caller is not in smart-tutor:eks-admin-principals (infra/cdk.json). kubectl and helm " +
            "will say Unauthorized, and the Kubernetes cleanup will fail.")
    }

    # Since #150 deploy.yml deploys native-cloud on a merge only while NATIVE_CLOUD_AUTO_DEPLOY is `true`, and since #282
    # only while the production switch PRODUCTION_DEPLOY is `true` as well. The script never changes either: they are
    # repository settings, so you do it.
    $AutoDeploy = gh variable get NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo 2>$null
    $ProductionDeploy = gh variable get PRODUCTION_DEPLOY --repo $Repo 2>$null
    if ($AutoDeploy -eq "true" -and -not ($ProductionDeploy -eq "true")) {
        Write-Host "NATIVE_CLOUD_AUTO_DEPLOY is 'true', but PRODUCTION_DEPLOY isn't 'true', so no merge deploys anything."
    }
    if ($AutoDeploy -eq "true" -and $ProductionDeploy -eq "true") {
        $SetCommand = "gh variable delete NATIVE_CLOUD_AUTO_DEPLOY --repo $Repo"
        if ($DryRun) {
            Write-Warning "NATIVE_CLOUD_AUTO_DEPLOY is 'true'; a real run would stop. Run first: $SetCommand"
        } else {
            throw "NATIVE_CLOUD_AUTO_DEPLOY is 'true', so the next merge to main would redeploy the pilot. Run: $SetCommand"
        }
    }

    # Objects, not arrays: PowerShell unrolls a result with a single row.
    $Query = "StackSummaries[?(starts_with(StackName,'SmartTutor-prod-') || StackName=='CDKToolkit') && " +
        "StackStatus!='DELETE_COMPLETE'].{Name:StackName,Status:StackStatus}"
    $Status = @{}
    foreach ($Row in Get-Json { aws cloudformation list-stacks --query $Query --output json }) { $Status[$Row.Name] = $Row.Status }
    Write-Host "`nStacks in the account:"
    $Status.GetEnumerator() | Sort-Object Name | ForEach-Object { Write-Host ("  {0,-34} {1}" -f $_.Name, $_.Value) }

    $ToDelete = @($DeleteStacks | Where-Object { $Status.ContainsKey($_) })
    Write-Host "`nWill DELETE: $(if ($ToDelete) { $ToDelete -join ', ' } else { '(none)' })" -ForegroundColor Red
    Write-Host "Will KEEP:" -ForegroundColor Green
    foreach ($Keep in $KeepStacks.GetEnumerator()) { Write-Host ("  {0,-34} {1}" -f $Keep.Key, $Keep.Value) -ForegroundColor Green }
    $Switches = @(if ($DeleteDatabaseSnapshots) { "RDS snapshots" }; if ($DeleteDocumentsBucket) { "documents bucket" };
        if ($DeleteLogGroups) { "log groups" })
    Write-Host "Irreversible extras: $(if ($Switches) { $Switches -join ', ' } else { 'none (leftovers are only reported)' })"

    # --- Confirmation --------------------------------------------------------------------------------------------
    if (-not (Confirm-Typed "This destroys the native-cloud pilot in account $AccountId." $AccountId)) {
        Write-Host "Cancelled."
        return
    }

    # --- Kubernetes cleanup --------------------------------------------------------------------------------------
    # The release, its TargetGroupBindings and the add-ons create security-group rules and ENIs outside CloudFormation.
    # They must go while the cluster and the controller still run, or the Edge and Network deletes fail.
    aws eks describe-cluster --name $ClusterName --query cluster.status --output text 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "`nCluster $ClusterName not found; skipping the Kubernetes cleanup"
    } else {
        Write-Host "`nKubernetes cleanup on $ClusterName"
        Invoke-Step "aws eks update-kubeconfig --name $ClusterName" {
            aws eks update-kubeconfig --name $ClusterName --region $Region | Out-Null
        }
        # Pin every command to this cluster's context, whatever kubectl's current context is later.
        $Ctx = if ($DryRun) { "(this cluster)" } else { kubectl config current-context }

        function Get-Release([string] $Name, [string] $Namespace) {
            $Found = helm list -n $Namespace --kube-context $Ctx --filter "^$Name`$" -q
            # An auth error must stop the run, not read as "not installed".
            if ($LASTEXITCODE -ne 0) { throw "helm list failed in $Namespace (exit code $LASTEXITCODE)" }
            return $Found
        }
        if ($DryRun -or (Get-Release smart-tutor smart-tutor)) {
            Invoke-Step "helm uninstall smart-tutor -n smart-tutor --wait" {
                helm uninstall smart-tutor -n smart-tutor --kube-context $Ctx --wait --timeout 10m
            }
        } else { Write-Host "Release smart-tutor not installed; skipping" }

        Invoke-Step "Wait until no TargetGroupBinding remains (the controller deregisters the targets)" {
            $Deadline = (Get-Date).AddMinutes(10)
            while ($true) {
                # A missing CRD means none are left; any other kubectl error stops the run.
                $Left = kubectl get targetgroupbindings -A --context $Ctx -o name 2>&1
                if ($LASTEXITCODE -ne 0) {
                    if ("$Left" -match "the server doesn't have a resource type") { break }
                    throw "kubectl get targetgroupbindings failed: $Left"
                }
                if (-not $Left) { break }
                if ((Get-Date) -gt $Deadline) { throw "TargetGroupBindings remain after 10 min: $($Left -join ', ')" }
                Write-Host "   waiting for: $($Left -join ', ')"
                Start-Sleep -Seconds 10
            }
            $global:LASTEXITCODE = 0
        }
        Invoke-Step "kubectl delete namespace smart-tutor" {
            kubectl delete namespace smart-tutor --context $Ctx --ignore-not-found --timeout 5m
        }
        foreach ($Addon in @(("aws-load-balancer-controller", "kube-system"), ("external-secrets", "external-secrets"),
                ("metrics-server", "kube-system"))) {
            if ($DryRun -or (Get-Release $Addon[0] $Addon[1])) {
                Invoke-Step "helm uninstall $($Addon[0]) -n $($Addon[1])" {
                    helm uninstall $Addon[0] -n $Addon[1] --kube-context $Ctx --wait
                }
            } else { Write-Host "Release $($Addon[0]) not installed; skipping" }
        }
    }

    # --- CloudFormation stacks -----------------------------------------------------------------------------------
    # --exclusively destroys only the stack named. Every native-cloud stack depends on Network, so without it a
    # destroy of Network would also destroy every stack that depends on it.
    # One call per stack keeps the order explicit. Rerunning is safe: it retries DELETE_FAILED stacks.
    $VpcId = $null
    if ("SmartTutor-prod-Network" -in $ToDelete) {
        # Read it now: the output is gone with the stack, and everything before the Network delete is scoped to it.
        $VpcId = aws cloudformation describe-stacks --stack-name SmartTutor-prod-Network `
            --query "Stacks[0].Outputs[?OutputKey=='VpcId'].OutputValue" --output text
        if ($LASTEXITCODE -ne 0 -or -not $VpcId -or $VpcId -eq "None") { throw "Network stack has no VpcId output" }
        Write-Host "`nVPC of the Network stack: $VpcId"
    }
    if ($ToDelete) {
        Write-Host "`nDestroying stacks (CloudFront alone takes about 15 min, the whole run 25 to 60 min)"
        Invoke-Step "uv sync (infra)" {
            Push-Location $InfraDir
            try { uv sync } finally { Pop-Location }
        }
        foreach ($Stack in $ToDelete) {
            if ($Stack -eq "SmartTutor-prod-Network") { Remove-VpcBlockers $VpcId }
            Invoke-Step "cdk destroy --exclusively $Stack" {
                Push-Location $InfraDir
                try {
                    npx --yes "aws-cdk@$CdkVersion" destroy --force --exclusively -c smart-tutor:mode=native-cloud $Stack
                } finally { Pop-Location }
            }
        }
    } else {
        Write-Host "`nNo native-cloud stacks to destroy"
    }

    # --- Leftovers -----------------------------------------------------------------------------------------------
    Write-Host "`nLeftovers$(if ($DryRun) { ' (a dry run has not destroyed anything yet, so the final snapshot is not there)' })"

    # Objects, not arrays: PowerShell unrolls a result with a single row.
    $SnapQuery = "DBSnapshots[?DBInstanceIdentifier=='$ClusterName'].{Id:DBSnapshotIdentifier,Gb:AllocatedStorage}"
    $Snapshots = @(Get-Json { aws rds describe-db-snapshots --snapshot-type manual --query $SnapQuery --output json })
    $SnapGb = ($Snapshots | Measure-Object -Property Gb -Sum).Sum
    Write-Host ("RDS manual and final snapshots: {0}" -f $(if ($Snapshots) {
        "$($Snapshots.Count), $SnapGb GiB, about `$$([math]::Round($SnapGb * 0.095, 2)) a month" } else { "none" }))
    $Snapshots | ForEach-Object { Write-Host "  $($_.Id)" }

    $Bucket = "smart-tutor-documents-$AccountId"
    aws s3api head-bucket --bucket $Bucket 2>$null | Out-Null
    $BucketExists = $LASTEXITCODE -eq 0
    if ($BucketExists) {
        $Listing = Get-Json { aws s3api list-object-versions --bucket $Bucket --max-items 1000 --output json }
        $Count = @($Listing.Versions | Where-Object { $_ }).Count + @($Listing.DeleteMarkers | Where-Object { $_ }).Count
        Write-Host ("Documents bucket {0}: {1}{2} object versions and delete markers (learner PDFs; S3 standard storage costs about `$0.023 per GB-month)" -f
            $Bucket, $Count, $(if ($Listing.NextToken) { "+" }))
    } else {
        Write-Host "Documents bucket ${Bucket}: not found"
    }

    $LogGroups = @(foreach ($Prefix in $LogGroupPrefixes) {
        Get-Json { aws logs describe-log-groups --log-group-name-prefix $Prefix --query "logGroups[].logGroupName" --output json }
    })
    Write-Host "Log groups ($($LogGroupPrefixes -join ', ')): $(if ($LogGroups) { $LogGroups.Count } else { 'none' })"
    $LogGroups | ForEach-Object { Write-Host "  $_" }

    # Exact names, not a prefix: on-premise keeps its secrets under smart-tutor-on-premise/.
    $Secrets = @(foreach ($SecretName in $SecretNames) {
        $Found = aws secretsmanager describe-secret --secret-id $SecretName --output json 2>$null
        if ($LASTEXITCODE -eq 0) { $Found | ConvertFrom-Json }
    })
    $Pending = @($Secrets | Where-Object DeletedDate)
    Write-Host "Secrets: $(if ($Secrets) { "$($Secrets.Count) left, $($Pending.Count) pending deletion" } else { 'none' })"
    $Secrets | ForEach-Object { Write-Host ("  {0}{1}" -f $_.Name, $(if ($_.DeletedDate) { "  (pending deletion)" })) }
    # A secret pending deletion still owns its name, so a redeploy that creates it again would fail.
    foreach ($Secret in $Pending) {
        Invoke-Step "Force-delete secret $($Secret.Name) (pending deletion)" {
            aws secretsmanager delete-secret --secret-id $Secret.Name --force-delete-without-recovery | Out-Null
        }
    }

    # --- Opt-in deletions ----------------------------------------------------------------------------------------
    if ($DeleteDatabaseSnapshots -and $Snapshots -and
        (Confirm-Typed "Permanently deletes $($Snapshots.Count) RDS snapshot(s): learner data, no recovery." "delete-snapshots")) {
        foreach ($Snap in $Snapshots) {
            Invoke-Step "Delete RDS snapshot $($Snap.Id)" { aws rds delete-db-snapshot --db-snapshot-identifier $Snap.Id | Out-Null }
        }
    }

    if ($DeleteDocumentsBucket -and $BucketExists -and
        (Confirm-Typed "Permanently deletes every learner PDF, all versions, in $Bucket." $Bucket)) {
        Invoke-Step "Empty (all versions and delete markers) and delete bucket $Bucket" {
            $Batch = Join-Path ([IO.Path]::GetTempPath()) "smart-tutor-teardown-$PID.json"
            try {
                while ($true) {
                    $Page = Get-Json { aws s3api list-object-versions --bucket $Bucket --max-items 1000 --output json }
                    $Objects = @(@($Page.Versions) + @($Page.DeleteMarkers) | Where-Object { $_ } |
                        ForEach-Object { @{ Key = $_.Key; VersionId = $_.VersionId } })
                    if (-not $Objects) { break }
                    @{ Objects = $Objects; Quiet = $true } | ConvertTo-Json -Depth 4 -Compress | Set-Content $Batch -Encoding utf8NoBOM
                    $Result = Get-Json { aws s3api delete-objects --bucket $Bucket --delete "file://$Batch" --output json }
                    if ($Result.Errors) { throw "S3 refused to delete: $($Result.Errors[0].Key) ($($Result.Errors[0].Message))" }
                    Write-Host "   deleted $($Objects.Count) versions"
                }
            } finally { Remove-Item $Batch -ErrorAction SilentlyContinue }
            aws s3api delete-bucket --bucket $Bucket
        }
    }

    if ($DeleteLogGroups -and $LogGroups -and
        (Confirm-Typed "Permanently deletes $($LogGroups.Count) log group(s)." "delete-logs")) {
        foreach ($Group in $LogGroups) {
            Invoke-Step "Delete log group $Group" { aws logs delete-log-group --log-group-name $Group }
        }
    }

    # --- Verify nothing expensive is left ------------------------------------------------------------------------
    if (-not $DryRun) {
        $Warnings = @()
        aws eks describe-cluster --name $ClusterName --query cluster.status --output text 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $Warnings += "EKS cluster $ClusterName still exists" }
        aws elbv2 describe-load-balancers --names $ClusterName --query "LoadBalancers[0].LoadBalancerArn" --output text 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $Warnings += "Load balancer $ClusterName still exists" }
        if ($VpcId) {
            $Nats = @(Get-Json { aws ec2 describe-nat-gateways --filter "Name=vpc-id,Values=$VpcId" "Name=state,Values=pending,available" `
                    --query "NatGateways[].NatGatewayId" --output json })
            if ($Nats) { $Warnings += "NAT gateway(s) still exist in ${VpcId}: $($Nats -join ', ')" }
        }
        $Warnings | ForEach-Object { Write-Warning "$_ (still costing money; fix the failed stack and run the script again)" }
        if (-not $Warnings) { Write-Host "No EKS cluster, load balancer or NAT gateway left" -ForegroundColor Green }
    }

    Write-Host ""
    Write-Host $(if ($DryRun) { "Dry run done. Nothing was changed." } else { "Done. Kept: $($KeepStacks.Keys -join ', ')." }) -ForegroundColor Green
} finally {
    foreach ($Name in $SavedEnv.Keys) { [Environment]::SetEnvironmentVariable($Name, $SavedEnv[$Name]) }
}
