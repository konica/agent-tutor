<#
.SYNOPSIS
    One-time AWS and GitHub setup for the pilot environment (#55, PRD Appendix A). See pilot-aws-prerequisites.md.

.DESCRIPTION
    Creates the GitHub OIDC provider, the deploy role smart-tutor-github-deploy, and the GitHub environment
    `pilot` with its variables, and optionally deletes a hand-made budget. Safe to run again: anything that
    already exists is left alone (the role's trust and inline policy are re-applied, so a rerun fixes drift).
    Run with -DryRun first to see what it would do.

.EXAMPLE
    ./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile default -DryRun
    ./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile default -DeleteBudget "My Monthly Cost Budget"
#>
[CmdletBinding()]
param(
    [string] $AwsProfile = "smart-tutor-admin",
    [string] $Region = "us-east-1",
    [string] $Repo = "konica/agent-tutor",
    [string] $Environment = "pilot",
    [string] $RoleName = "smart-tutor-github-deploy",
    [string] $DeleteBudget,
    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false   # we check $LASTEXITCODE ourselves

$env:AWS_PROFILE = $AwsProfile
$env:AWS_REGION = $Region

function Invoke-Step([string] $Description, [scriptblock] $Action) {
    if ($DryRun) { Write-Host "[dry run] $Description" -ForegroundColor Yellow; return }
    Write-Host "-> $Description" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Description (exit code $LASTEXITCODE)" }
}

# --- Who and where -------------------------------------------------------------------------------------------
$AccountId = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0) { throw "No AWS credentials for profile '$AwsProfile'. Sign in first (step 1)." }
$Caller = aws sts get-caller-identity --query Arn --output text
Write-Host "AWS account $AccountId as $Caller, region $Region"

$SubPrefix = gh api "repos/$Repo/actions/oidc/customization/sub" --jq '.sub_claim_prefix // empty'
if ($LASTEXITCODE -ne 0) { throw "gh can't read $Repo. Run 'gh auth login' with a repo admin account." }
if (-not $SubPrefix) { $SubPrefix = "repo:$Repo" }
$Subject = "${SubPrefix}:environment:$Environment"
Write-Host "GitHub OIDC subject: $Subject"

$Work = Join-Path ([IO.Path]::GetTempPath()) "smart-tutor-aws-setup"
New-Item -ItemType Directory -Force $Work | Out-Null

# --- Step 3a: GitHub OIDC provider ---------------------------------------------------------------------------
$ProviderArn = "arn:aws:iam::${AccountId}:oidc-provider/token.actions.githubusercontent.com"
$Providers = aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[].Arn" --output text
if ($Providers -match [regex]::Escape($ProviderArn)) {
    Write-Host "OIDC provider exists: $ProviderArn"
} else {
    Invoke-Step "Create OIDC provider token.actions.githubusercontent.com" {
        aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com `
            --client-id-list sts.amazonaws.com | Out-Null
    }
}

# --- Step 3c-d: deploy role ----------------------------------------------------------------------------------
$Trust = @{
    Version   = "2012-10-17"
    Statement = @(@{
        Effect    = "Allow"
        Principal = @{ Federated = $ProviderArn }
        Action    = "sts:AssumeRoleWithWebIdentity"
        Condition = @{ StringEquals = @{
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
            "token.actions.githubusercontent.com:sub" = $Subject
        } }
    })
}
$Policy = @{
    Version   = "2012-10-17"
    Statement = @(
        @{ Sid = "AssumeCdkBootstrapRoles"; Effect = "Allow"; Action = "sts:AssumeRole"
           Resource = "arn:aws:iam::${AccountId}:role/cdk-hnb659fds-*-${AccountId}-$Region" },
        @{ Sid = "EcrLogin"; Effect = "Allow"; Action = "ecr:GetAuthorizationToken"; Resource = "*" },
        @{ Sid = "EcrPushAppImages"; Effect = "Allow"
           Action = @("ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
                      "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
                      "ecr:PutImage", "ecr:DescribeImages")
           Resource = "arn:aws:ecr:${Region}:${AccountId}:repository/smart-tutor/*" },
        @{ Sid = "EksKubeconfig"; Effect = "Allow"; Action = "eks:DescribeCluster"
           Resource = "arn:aws:eks:${Region}:${AccountId}:cluster/smart-tutor-*" },
        @{ Sid = "ReadStackOutputs"; Effect = "Allow"; Action = "cloudformation:DescribeStacks"
           Resource = "arn:aws:cloudformation:${Region}:${AccountId}:stack/SmartTutor-prod-*/*" }
    )
}
$TrustFile = Join-Path $Work "trust.json"
$PolicyFile = Join-Path $Work "deploy-policy.json"
# UTF-8 without BOM: the AWS CLI rejects a BOM in policy documents.
[IO.File]::WriteAllText($TrustFile, ($Trust | ConvertTo-Json -Depth 10))
[IO.File]::WriteAllText($PolicyFile, ($Policy | ConvertTo-Json -Depth 10))
if ($DryRun) {
    Write-Host "Trust policy ($TrustFile):"; Get-Content $TrustFile
    Write-Host "Deploy policy ($PolicyFile):"; Get-Content $PolicyFile
}

aws iam get-role --role-name $RoleName --query Role.Arn --output text 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Invoke-Step "Update trust policy of existing role $RoleName" {
        aws iam update-assume-role-policy --role-name $RoleName --policy-document "file://$TrustFile"
    }
} else {
    Invoke-Step "Create role $RoleName" {
        aws iam create-role --role-name $RoleName --max-session-duration 3600 `
            --description "GitHub Actions ($Repo, environment $Environment) deploys the pilot" `
            --assume-role-policy-document "file://$TrustFile" | Out-Null
    }
}
Invoke-Step "Put inline policy 'deploy' on $RoleName" {
    aws iam put-role-policy --role-name $RoleName --policy-name deploy --policy-document "file://$PolicyFile"
}
$RoleArn = "arn:aws:iam::${AccountId}:role/$RoleName"

# --- Step 4: GitHub environment, main only, with variables --------------------------------------------------
Invoke-Step "Create or update GitHub environment '$Environment' (custom branch policy)" {
    gh api -X PUT "repos/$Repo/environments/$Environment" `
        -F "deployment_branch_policy[protected_branches]=false" `
        -F "deployment_branch_policy[custom_branch_policies]=true" | Out-Null
}
$Branches = if ($DryRun) { "" } else {
    gh api "repos/$Repo/environments/$Environment/deployment-branch-policies" --jq '.branch_policies[].name'
}
if ($Branches -contains "main") {
    Write-Host "Environment '$Environment' already deploys from main"
} else {
    Invoke-Step "Allow deployments to '$Environment' from main only" {
        gh api -X POST "repos/$Repo/environments/$Environment/deployment-branch-policies" `
            -f name=main -f type=branch | Out-Null
    }
}
Invoke-Step "Set environment variables AWS_ROLE_ARN, AWS_REGION, AWS_ACCOUNT_ID" {
    gh variable set AWS_ROLE_ARN --repo $Repo --env $Environment --body $RoleArn
    gh variable set AWS_REGION --repo $Repo --env $Environment --body $Region
    gh variable set AWS_ACCOUNT_ID --repo $Repo --env $Environment --body $AccountId
}

# --- Step 5: remove a hand-made budget -----------------------------------------------------------------------
if ($DeleteBudget) {
    $Existing = aws budgets describe-budgets --account-id $AccountId --query "Budgets[].BudgetName" --output json |
        ConvertFrom-Json
    if ($Existing -contains $DeleteBudget) {
        Invoke-Step "Delete budget '$DeleteBudget'" {
            aws budgets delete-budget --account-id $AccountId --budget-name $DeleteBudget
        }
    } else {
        Write-Host "Budget '$DeleteBudget' not found; nothing to delete"
    }
}

Remove-Item -Recurse -Force $Work
Write-Host ""
Write-Host "Done. Deploy role: $RoleArn" -ForegroundColor Green
Write-Host "Trusted subject:   $Subject"
