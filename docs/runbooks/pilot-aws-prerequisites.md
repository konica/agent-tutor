# Pilot environment on AWS: human steps

Checklist for #55, the one-time AWS setup for the pilot environment (#54, PRD §9.11, §9.12, Appendix A). It needs an account admin. The agent slices #56–#59 need a few more human actions, listed at the end. When #56 writes the deploy runbook, it absorbs this file.

For the big picture (GitHub and AWS trust, runtime request flow, deploy on merge, which slice builds what), see [`pilot-environment-overview.md`](pilot-environment-overview.md).

Commands are for **PowerShell 7** (`pwsh`) on Windows. Run them from the repository root.

**What's code and what's by hand.** The AWS side is infrastructure as code. The OIDC provider and the deploy role are the CDK stack `SmartTutor-prod-GitHubDeploy` ([`infra/smart_tutor_infra/stacks/github_deploy.py`](../../infra/smart_tutor_infra/stacks/github_deploy.py)), reviewed and tested like every other stack. An admin deploys it once from a laptop, because GitHub Actions can't create the role it signs in with; after that, the deploy workflow (#59) keeps it up to date. The rest can't be CDK: `cdk bootstrap` must exist before any CDK deploy, the GitHub environment lives on GitHub rather than AWS, and quotas and the budget amount are checks and decisions. [`pilot-aws-prerequisites.ps1`](pilot-aws-prerequisites.ps1) does steps 2–4 in one go. You can run it again safely, and it has a `-DryRun` switch.

## Names the later slices depend on

The deploy role's permissions use these names, so #56–#59 must use them too. If you change a name here, change it in the script and everywhere else.

| What | Name |
|---|---|
| Region | `us-east-1` |
| Admin CLI profile (your laptop) | `smart-tutor-admin` (any admin profile works; pass it with `-AwsProfile`) |
| GitHub Actions deploy role | `smart-tutor-github-deploy` |
| GitHub environment | `pilot` (deploys from `main` only) |
| ECR repositories | `smart-tutor/<service>` (`api`, `web`, `keycloak`; later `agent`, `mcp`, `worker`) |
| EKS cluster | `smart-tutor-prod` |
| CloudFormation stacks | `SmartTutor-prod-*` (already set in `infra/smart_tutor_infra/app_stacks.py`) |

## 0. Tools on your laptop

| Tool | Check | Needed for |
|---|---|---|
| PowerShell 7 | `$PSVersionTable.PSVersion` | this checklist |
| AWS CLI v2 | `aws --version` | everything |
| Node 22+ | `node --version` | the CDK CLI (`npx aws-cdk`) |
| uv | `uv --version` | the CDK app in `infra/` |
| gh (signed in, repo admin) | `gh auth status` | the GitHub environment |
| kubectl, helm | `kubectl version --client`, `helm version` | #56 onwards, not #55 |
| Docker | `docker version` | #56 onwards (image builds) |

If PowerShell refuses to run the script because of the execution policy, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or start the script with `pwsh -ExecutionPolicy Bypass -File <script>`.

## 1. Admin access to the AWS account (about 10 min)

1. Make sure the root user has MFA and you don't use it day to day.
2. Get an admin identity. Prefer IAM Identity Center with the `AdministratorAccess` permission set, then:
   ```powershell
   aws configure sso --profile smart-tutor-admin      # SSO start URL, region us-east-1, the account, AdministratorAccess
   aws sso login --profile smart-tutor-admin
   ```
   Without Identity Center, use `aws login --profile smart-tutor-admin` (AWS CLI 2.32 or later) with an IAM principal that has admin rights.
3. Check it and save the values for the record in step 7:
   ```powershell
   $env:AWS_PROFILE = "smart-tutor-admin"; $env:AWS_REGION = "us-east-1"
   aws sts get-caller-identity
   $AccountId = aws sts get-caller-identity --query Account --output text
   $AccountId
   ```
   Record the `Arn`. For an SSO session it looks like `arn:aws:sts::<ACCOUNT_ID>:assumed-role/AWSReservedSSO_AdministratorAccess_<hash>/<you>`. #56 grants the matching **role** ARN (`arn:aws:iam::<ACCOUNT_ID>:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_<hash>`) access to the EKS cluster, so you can run `kubectl` and `helm` from your laptop. Look it up with:
   ```powershell
   aws iam list-roles --query "Roles[?starts_with(RoleName,'AWSReservedSSO_AdministratorAccess')].Arn" --output text
   ```
   If the admin is an IAM **user** with access keys (for example `arn:aws:iam::<ACCOUNT_ID>:user/poweruser`), the `Arn` from `get-caller-identity` is already the principal to record. In that case, turn on MFA for the user, and don't use the same admin key as the developer profile that Compose mounts into containers. A separate developer user with only Bedrock rights is safer.

Keep `$env:AWS_PROFILE`, `$env:AWS_REGION` and `$AccountId` set in this PowerShell window for the rest of this checklist.

## 2. Bootstrap CDK in us-east-1 (about 5 min)

```powershell
Push-Location infra
uv sync
npx aws-cdk@latest bootstrap "aws://$AccountId/us-east-1"
Pop-Location
```

This creates the `CDKToolkit` stack: an S3 bucket and an ECR repository for CDK assets, and four roles named `cdk-hnb659fds-{deploy,file-publishing,image-publishing,lookup}-role-<ACCOUNT_ID>-us-east-1`. CloudFormation deploys with `AdministratorAccess` by default. That is fine for a single-purpose pilot account. In a shared account, pass `--cloudformation-execution-policies <narrower policy ARN>`.

Check:

```powershell
aws cloudformation describe-stacks --stack-name CDKToolkit --query "Stacks[0].StackStatus" --output text   # CREATE_COMPLETE
aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version --query Parameter.Value --output text
```

## 3–4. Deploy role and GitHub environment: run the script (about 5 min)

```powershell
./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile smart-tutor-admin -DryRun   # read-only; prints the cdk diff and the planned changes
./docs/runbooks/pilot-aws-prerequisites.ps1 -AwsProfile smart-tutor-admin
```

Add `-DeleteBudget "<name>"` to also remove a hand-made budget (see step 5). If step 2 hasn't run yet, the script bootstraps CDK first. Then it does the following.

### 3a. Checks the repository's OIDC subject against `infra/cdk.json`

```powershell
gh api repos/konica/agent-tutor/actions/oidc/customization/sub
```

This repository uses GitHub's **immutable** subject: the answer has `"use_immutable_subject":true` and `"sub_claim_prefix":"repo:konica@1114311/agent-tutor@1399048529"` (owner and repository IDs, so a renamed or re-created repo can't inherit the trust). A job in the `pilot` environment gets the subject `repo:konica@1114311/agent-tutor@1399048529:environment:pilot`. `infra/cdk.json` holds the prefix (`smart-tutor:github-oidc-subject-prefix`) and the environment name (`smart-tutor:github-environment`). The script stops if the prefix differs from GitHub's.

### 3b. Deploys `SmartTutor-prod-GitHubDeploy`: the OIDC provider

The stack creates the IAM OIDC provider for `https://token.actions.githubusercontent.com` with audience `sts.amazonaws.com`. An account can hold only one such provider. If another tool already created it, put its ARN in `infra/cdk.json` as `smart-tutor:github-oidc-provider-arn`, and the stack imports it instead (the script tells you).

### 3c. … and the role `smart-tutor-github-deploy`

The role trusts **only jobs in the `pilot` environment** (`StringEquals` on `aud` and `sub`). Step 4 limits that environment to the `main` branch, so a pull request or another branch can never assume it. Together this is the "only `main` and environment-protected jobs" rule from #55 and #59. Maximum session: 1 hour.

### 3d. Gives it only what deployment needs (inline policy `deploy`)

| Permission | Resource | Why |
|---|---|---|
| `sts:AssumeRole` | `cdk-hnb659fds-*-<ACCOUNT_ID>-us-east-1` | `cdk deploy` works through the CDK bootstrap roles, so the deploy role never gets CloudFormation or IAM rights directly |
| `ecr:GetAuthorizationToken` | `*` | `docker login` to ECR (this action has no resource) |
| ECR push and pull actions | `smart-tutor/*` repositories | push app images |
| `eks:DescribeCluster` | `smart-tutor-*` clusters | `aws eks update-kubeconfig`. Kubernetes permissions come from an **EKS access entry**, which #56 creates in CDK for this role. |
| `cloudformation:DescribeStacks` | `SmartTutor-prod-*` stacks | the #59 smoke test reads the CloudFront address from the stack outputs |

If #59 finds a missing permission, add it to `github_deploy.py` with a specific resource, never `*` on a service, and extend `infra/tests/test_synth.py`. The merge deploys it.

### 4. Creates the GitHub environment `pilot`

- **Deployment branches:** `main` only (custom branch policy).
- **Variables:** `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_ACCOUNT_ID`. There are no AWS keys to store, because OIDC replaces them.

Optional: in **Settings → Environments → pilot**, add **Required reviewers** if every deploy should wait for an approval.

The deploy workflow in #59 declares `environment: pilot`, `permissions: id-token: write`, and calls `aws-actions/configure-aws-credentials` with `role-to-assume: ${{ vars.AWS_ROLE_ARN }}`. Nothing here can be tested end to end before #59, but a wrong `sub` or a missing environment shows up there as `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

### Check

```powershell
aws iam get-role --role-name smart-tutor-github-deploy --query "Role.[Arn,AssumeRolePolicyDocument.Statement[0].Condition]" --output json
aws iam get-role-policy --role-name smart-tutor-github-deploy --policy-name deploy --query "PolicyDocument.Statement[].Sid" --output text
gh api repos/konica/agent-tutor/environments/pilot --jq "{name, deployment_branch_policy}"
gh api repos/konica/agent-tutor/environments/pilot/deployment-branch-policies --jq ".branch_policies[].name"   # main
gh variable list --repo konica/agent-tutor --env pilot
```

## 5. Decide the budget and the alert email (decision, about 5 min)

The idle cost is about **$250–300 a month**: EKS control plane, 2 nodes, NAT gateway, RDS, internal load balancer, CloudFront. Bedrock costs come on top once the agent and worker are enabled.

Decide:

- **Monthly budget amount.** Suggested: **$400**, which covers idle cost plus light Bedrock use.
- **Alert recipients.** One or more email addresses, ideally a shared inbox rather than one person.
- **Thresholds.** Suggested: email at 80% of **actual** spend and at 100% of **forecasted** spend.

Check for budgets someone created by hand:

```powershell
aws budgets describe-budgets --account-id $AccountId --query "Budgets[].[BudgetName,BudgetLimit.Amount]" --output text
```

A small account-wide budget will alert within days once the pilot runs. Delete it (the script's `-DeleteBudget "<name>"`, or `aws budgets delete-budget --account-id $AccountId --budget-name "<name>"`), raise it, or note that it stays.

#56 creates the budget in `BudgetsStack` from these values. Budget emails go straight to the addresses, with no subscription to confirm. Optional: in **Billing → Cost Explorer**, enable Cost Explorer now, because it takes up to 24 hours to show data.

## 6. Confirm the service quotas (about 5 min, longer if an increase is needed)

The pilot needs one EKS cluster with a managed node group of 2 small nodes (2–4 vCPU each), one NAT gateway with one Elastic IP, and one new VPC. Node upgrades briefly add extra nodes, so plan for at least **16 vCPU**.

```powershell
function Get-Quota($Service, $Code) {
    aws service-quotas get-service-quota --service-code $Service --quota-code $Code --query "Quota.[QuotaName,Value]" --output text
}
Get-Quota ec2 L-1216C47A    # Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances, in vCPUs; need >= 16
Get-Quota ec2 L-0263D0A3    # EC2-VPC Elastic IPs; need 1 free
Get-Quota vpc L-F678F1CE    # VPCs per Region; need 1 free
aws service-quotas list-service-quotas --service-code eks `
    --query "Quotas[?QuotaName=='Clusters' || QuotaName=='Managed node groups per cluster'].[QuotaName,Value]" --output text

# Current usage, to compare with the "free" requirements above
aws ec2 describe-vpcs --query "length(Vpcs)"
aws ec2 describe-addresses --query "length(Addresses)"
aws eks list-clusters --query "length(clusters)"
```

If the vCPU quota is below 16, request an increase. Approval usually takes minutes to a day.

```powershell
aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 16
aws service-quotas list-requested-service-quota-change-history --service-code ec2 `
    --query "RequestedQuotas[].[QuotaCode,DesiredValue,Status]" --output text
```

A brand-new account may also be "pending verification" for EC2. If launching nodes later fails with that message, open a support case.

## 7. Record the results on #55

Fill this in and post it, then tick the acceptance criteria on #55:

```powershell
$Record = @'
## AWS prerequisites — done

| Item | Value |
|---|---|
| Account ID | <ACCOUNT_ID> |
| Region | us-east-1 |
| CDK bootstrap | CDKToolkit stack, bootstrap version <N>, done <date> |
| Admin principal for EKS access (#56) | <admin role or user ARN from step 1> |
| GitHub deploy role | arn:aws:iam::<ACCOUNT_ID>:role/smart-tutor-github-deploy (trusts repo:konica@1114311/agent-tutor@1399048529:environment:pilot) |
| GitHub environment | pilot, deployment branches: main; required reviewers: <yes/no>; vars AWS_ROLE_ARN, AWS_REGION, AWS_ACCOUNT_ID |
| Monthly budget | $<amount> |
| Budget alert email(s) | <address(es)> |
| Budget thresholds | 80% actual, 100% forecasted |
| EC2 on-demand vCPU quota | <value> (increase requested: <yes/no, case id>) |
| Elastic IPs / VPCs / EKS clusters | <quota> / <quota> / <quota>, in use <n> / <n> / <n> |

Steps followed: docs/runbooks/pilot-aws-prerequisites.md
'@
$Record | gh issue comment 55 --repo konica/agent-tutor --body-file -
```

The account ID isn't a secret, but don't post access keys, session tokens or passwords on the issue.

## Not needed for #54 (Appendix A items deferred)

The pilot runs only web, API, Keycloak and `migrate`, so these Appendix A items can wait until the agent, MCP server and worker are enabled on AWS:

- Item 2: Bedrock model access for the agent and worker models in this account. Developers already use them locally.
- Item 3: Bedrock quotas for ingestion plus 50 concurrent learners.
- Item 7: PrivateLink for `bedrock-runtime`, an optional Guardrail, the seed corpus license check, and data-erasure obligations.
- Item 4 (domain, DNS, ACM) is replaced by the CloudFront address (#54 decisions). #56 records this in an ADR and the PRD.

## Human steps in the later slices

The agent builds #56–#59; a human still does these:

| Slice | Human action |
|---|---|
| #56 public web app | Review and merge the PR. Run the first `cdk deploy` and add-on install from your laptop with your admin profile, following the runbook the slice writes. Open the CloudFront address and check that the app shell loads and the load balancer has no public address. Check that the budget email address is right in the Budgets console. |
| #57 Keycloak | Get the Keycloak admin password from Secrets Manager (the secret name is in the #57 runbook) and sign in at `https://<id>.cloudfront.net/auth/admin`. Create the client's account: realm **smart-tutor** → **Users → Add user** → email, first and last name, **Email verified** on → **Create** → **Credentials → Set password** with **Temporary** on, so the client chooses their own password at first sign-in. To remove access, **disable** the user (Users → user → Enabled off); the PRD has no account-deletion function yet. Do the #57 demo: the new user signs in to `/auth/realms/smart-tutor/account`. |
| #58 sign-in end to end | Run or watch the demo against the public address: sign-in reaches the Library with the user's name; `GET /api/me` with the token gives 200; after sign-out the token gets 401; without a token, 401 with `WWW-Authenticate: Bearer`. Then send the client the address and username, and the temporary password **through a separate channel**. **The client has access from here.** |
| #59 deploy on merge | Merge the workflow PR. If you turned on required reviewers, approve the `pilot` deployment in the Actions run. Check that the first run's smoke test passes. Practice one rollback to the previous image tag, following the runbook. |

### Cost control while the pilot is idle

The environment costs about $250–300 a month even with no traffic. If the pilot pauses for weeks, tear it down with the `cdk destroy` steps in the #56 runbook. RDS needs a final snapshot, because documents and threads are never deleted (PRD lifecycle invariant). The prerequisites in this file (bootstrap, OIDC role, GitHub environment) can stay. They cost nothing.
