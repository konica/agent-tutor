<#
.SYNOPSIS
    One-time AWS and GitHub setup for the pilot environment (#55, PRD Appendix A). See pilot-aws-prerequisites.md.

.DESCRIPTION
    1. Bootstraps CDK in the account and region, unless the CDKToolkit stack already exists.
    2. Deploys the CDK stack SmartTutor-prod-GitHubDeploy: the GitHub OIDC provider and the deploy role
       smart-tutor-github-deploy (infra/smart_tutor_infra/stacks/github_deploy.py).
    3. Creates the GitHub environment `pilot`, limited to `main`, with the variables the deploy workflow reads.
    4. Optionally deletes a hand-made budget.
    Safe to run again. Run with -DryRun first: it only reads (AWS and GitHub), prints the template-only cdk diff, and
    lists what it would do.

.EXAMPLE
    ./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile default -DryRun
    ./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile default -DeleteBudget "My Monthly Cost Budget"
#>
[CmdletBinding()]
param(
    [string] $AwsProfile = "smart-tutor-admin",
    [string] $Region = "us-east-1",
    [string] $Repo = "konica/agent-tutor",
    [string] $DeleteBudget,
    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$PSNativeCommandUseErrorActionPreference = $false   # we check $LASTEXITCODE ourselves

$RepoRoot = (Resolve-Path "$PSScriptRoot/../..").Path
$InfraDir = Join-Path $RepoRoot "infra"
$Stack = "SmartTutor-prod-GitHubDeploy"
$env:AWS_PROFILE = $AwsProfile
$env:AWS_REGION = $Region
$env:JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = "1"

function Invoke-Step([string] $Description, [scriptblock] $Action) {
    if ($DryRun) { Write-Host "[dry run] $Description" -ForegroundColor Yellow; return }
    Write-Host "-> $Description" -ForegroundColor Cyan
    & $Action
    if ($LASTEXITCODE -ne 0) { throw "Failed: $Description (exit code $LASTEXITCODE)" }
}

function Test-Stack([string] $Name) {
    aws cloudformation describe-stacks --stack-name $Name --query "Stacks[0].StackStatus" --output text 2>$null |
        Out-Null
    return $LASTEXITCODE -eq 0
}

# --- Who and where -------------------------------------------------------------------------------------------
$AccountId = aws sts get-caller-identity --query Account --output text
if ($LASTEXITCODE -ne 0) { throw "No AWS credentials for profile '$AwsProfile'. Sign in first (step 1)." }
$Caller = aws sts get-caller-identity --query Arn --output text
Write-Host "AWS account $AccountId as $Caller, region $Region"

# The deploy role trusts the subject prefix and environment in infra/cdk.json. Check they match GitHub's view.
$Context = (Get-Content (Join-Path $InfraDir "cdk.json") -Raw | ConvertFrom-Json).context
$Environment = $Context."smart-tutor:github-environment"
$ConfiguredPrefix = $Context."smart-tutor:github-oidc-subject-prefix"
$GitHubPrefix = gh api "repos/$Repo/actions/oidc/customization/sub" --jq '.sub_claim_prefix // empty'
if ($LASTEXITCODE -ne 0) { throw "gh can't read $Repo. Run 'gh auth login' with a repo admin account." }
if (-not $GitHubPrefix) { $GitHubPrefix = "repo:$Repo" }
if ($GitHubPrefix -ne $ConfiguredPrefix) {
    throw "GitHub issues OIDC subjects starting '$GitHubPrefix', but infra/cdk.json has '$ConfiguredPrefix'. " +
        "Fix smart-tutor:github-oidc-subject-prefix in infra/cdk.json first."
}
Write-Host "Deploy role will trust: ${ConfiguredPrefix}:environment:$Environment"

# --- Step 2: CDK bootstrap -----------------------------------------------------------------------------------
if (Test-Stack "CDKToolkit") {
    Write-Host "CDK already bootstrapped (CDKToolkit exists)"
} else {
    Invoke-Step "cdk bootstrap aws://$AccountId/$Region" {
        Push-Location $InfraDir
        try { npx -y aws-cdk@latest bootstrap "aws://$AccountId/$Region" } finally { Pop-Location }
    }
}

# --- Step 3: OIDC provider and deploy role, from CDK ---------------------------------------------------------
# The account can hold only one provider for GitHub. If one exists and our stack didn't create it, the stack must
# import it (infra/cdk.json: smart-tutor:github-oidc-provider-arn), or the deploy fails.
$ProviderArn = "arn:aws:iam::${AccountId}:oidc-provider/token.actions.githubusercontent.com"
$Providers = aws iam list-open-id-connect-providers --query "OpenIDConnectProviderList[].Arn" --output text
$StackExists = Test-Stack $Stack
if (($Providers -match [regex]::Escape($ProviderArn)) -and -not $StackExists -and
    -not $Context."smart-tutor:github-oidc-provider-arn") {
    throw "A GitHub OIDC provider already exists ($ProviderArn). Add `"smart-tutor:github-oidc-provider-arn`": " +
        "`"$ProviderArn`" to the context in infra/cdk.json, commit it, and run this script again."
}
if ($DryRun -and (Test-Path (Join-Path $InfraDir ".venv"))) {
    Push-Location $InfraDir
    try {
        Write-Host "Changes cdk deploy would make to ${Stack}:"
        # Template-only diff: the default method uploads the template and creates a temporary stack for a change set.
        npx -y aws-cdk@latest diff $Stack --method=template
    } finally { Pop-Location }
}
Invoke-Step "cdk deploy $Stack (OIDC provider, role smart-tutor-github-deploy)" {
    Push-Location $InfraDir
    try { npx -y aws-cdk@latest deploy $Stack --require-approval never } finally { Pop-Location }
}
$RoleArn = if ($DryRun -and -not $StackExists) { "arn:aws:iam::${AccountId}:role/smart-tutor-github-deploy" } else {
    aws cloudformation describe-stacks --stack-name $Stack `
        --query "Stacks[0].Outputs[?OutputKey=='DeployRoleArn'].OutputValue" --output text
}

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
Invoke-Step "Set environment variables AWS_ROLE_ARN=$RoleArn, AWS_REGION, AWS_ACCOUNT_ID" {
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

Write-Host ""
Write-Host "Done. Deploy role: $RoleArn" -ForegroundColor Green
