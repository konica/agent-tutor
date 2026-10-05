# Pilot environment on AWS: human steps

Checklist for the human work in #54 (PRD §9.11, §9.12, Appendix A). Most of it is #55, the one-time AWS setup that needs an account admin. The agent slices #56–#59 need a few more human actions, listed at the end. When #56 writes the deploy runbook, it absorbs this file.

Commands are for **Git Bash** on Windows (they also work on macOS and Linux). Run them from the repository root. Replace `<ACCOUNT_ID>` and other placeholders as you go.

## Names the later slices depend on

The deploy role's permissions use these names, so #56–#59 must use them too. If you change a name here, change it everywhere.

| What | Name |
|---|---|
| Region | `us-east-1` |
| Admin CLI profile (your laptop) | `smart-tutor-admin` |
| GitHub Actions deploy role | `smart-tutor-github-deploy` |
| GitHub environment | `pilot` (deploys from `main` only) |
| ECR repositories | `smart-tutor/<service>` (`api`, `web`, `keycloak`; later `agent`, `mcp`, `worker`) |
| EKS cluster | `smart-tutor-prod` |
| CloudFormation stacks | `SmartTutor-prod-*` (already set in `infra/smart_tutor_infra/app_stacks.py`) |

## 0. Tools on your laptop

| Tool | Check | Needed for |
|---|---|---|
| AWS CLI v2 | `aws --version` | everything |
| Node 22+ | `node --version` | the CDK CLI (`npx aws-cdk`) |
| uv | `uv --version` | the CDK app in `infra/` |
| gh (signed in, repo admin) | `gh auth status` | the GitHub environment |
| kubectl, helm | `kubectl version --client`, `helm version` | #56 onwards, not #55 |
| Docker | `docker version` | #56 onwards (image builds) |

## 1. Admin access to the AWS account (about 10 min)

1. Make sure the root user has MFA and you don't use it day to day.
2. Get an admin identity. Prefer IAM Identity Center with the `AdministratorAccess` permission set, then:
   ```bash
   aws configure sso --profile smart-tutor-admin      # SSO start URL, region us-east-1, the account, AdministratorAccess
   aws sso login --profile smart-tutor-admin
   ```
   Without Identity Center, use `aws login --profile smart-tutor-admin` (AWS CLI 2.32 or later) with an IAM principal that has admin rights.
3. Check it and save the values for the record in step 7:
   ```bash
   export AWS_PROFILE=smart-tutor-admin AWS_REGION=us-east-1
   aws sts get-caller-identity
   export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
   echo $ACCOUNT_ID
   ```
   Record the `Arn`. For an SSO session it looks like `arn:aws:sts::<ACCOUNT_ID>:assumed-role/AWSReservedSSO_AdministratorAccess_<hash>/<you>`. #56 grants the matching **role** ARN (`arn:aws:iam::<ACCOUNT_ID>:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_<hash>`) access to the EKS cluster, so you can run `kubectl` and `helm` from your laptop. Look it up with:
   ```bash
   aws iam list-roles --query "Roles[?starts_with(RoleName,'AWSReservedSSO_AdministratorAccess')].Arn" --output text
   ```

Keep `AWS_PROFILE`, `AWS_REGION` and `ACCOUNT_ID` exported for the rest of this checklist.

## 2. Bootstrap CDK in us-east-1 (about 5 min)

```bash
cd infra
uv sync
npx aws-cdk@latest bootstrap aws://$ACCOUNT_ID/us-east-1
cd ..
```

This creates the `CDKToolkit` stack: an S3 bucket and an ECR repository for CDK assets, and four roles named `cdk-hnb659fds-{deploy,file-publishing,image-publishing,lookup}-role-<ACCOUNT_ID>-us-east-1`. CloudFormation deploys with `AdministratorAccess` by default. That is fine for a single-purpose pilot account. In a shared account, pass `--cloudformation-execution-policies <narrower policy ARN>`.

Check:

```bash
aws cloudformation describe-stacks --stack-name CDKToolkit --query "Stacks[0].StackStatus" --output text   # CREATE_COMPLETE
MSYS_NO_PATHCONV=1 aws ssm get-parameter --name /cdk-bootstrap/hnb659fds/version --query Parameter.Value --output text
```

## 3. GitHub Actions deploy role, trusted through OIDC (about 15 min)

### 3a. Trust GitHub's OIDC provider (once per account)

```bash
aws iam list-open-id-connect-providers     # skip the next command if token.actions.githubusercontent.com is listed
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

AWS no longer checks the thumbprint for this provider. If an older CLI insists on one, add `--thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1`.

### 3b. Check the repository's OIDC subject format

```bash
gh api repos/konica/agent-tutor/actions/oidc/customization/sub
```

Expect `{"use_default":true}`. A job in the `pilot` environment then gets the subject `repo:konica/agent-tutor:environment:pilot`. If the organization uses a custom subject template, change the `sub` value in 3c to match.

### 3c. Create the role

The role trusts **only jobs in the `pilot` environment**. Step 4 limits that environment to the `main` branch, so a pull request or another branch can never assume it. Together this is the "only `main` and environment-protected jobs" rule from #55 and #59.

```bash
mkdir -p .aws-setup     # scratch folder, ignored by Git

cat > .aws-setup/trust.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:konica/agent-tutor:environment:pilot"
      }
    }
  }]
}
EOF

aws iam create-role \
  --role-name smart-tutor-github-deploy \
  --description "GitHub Actions (konica/agent-tutor, environment pilot) deploys the pilot" \
  --max-session-duration 3600 \
  --assume-role-policy-document file://.aws-setup/trust.json
```

### 3d. Give it only what deployment needs

- `cdk deploy` uses the **CDK bootstrap roles**, so the deploy role only needs to assume them. It never gets CloudFormation or IAM rights directly.
- The pipeline pushes app images to the `smart-tutor/*` ECR repositories.
- `aws eks update-kubeconfig` needs `eks:DescribeCluster`. Kubernetes permissions come from an **EKS access entry**, which #56 creates in CDK for this role.
- The smoke test in #59 reads the CloudFront address from the stack outputs.

```bash
cat > .aws-setup/deploy-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "AssumeCdkBootstrapRoles", "Effect": "Allow", "Action": "sts:AssumeRole",
      "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/cdk-hnb659fds-*-${ACCOUNT_ID}-us-east-1" },
    { "Sid": "EcrLogin", "Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*" },
    { "Sid": "EcrPushAppImages", "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer",
        "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload",
        "ecr:PutImage", "ecr:DescribeImages"
      ],
      "Resource": "arn:aws:ecr:us-east-1:${ACCOUNT_ID}:repository/smart-tutor/*" },
    { "Sid": "EksKubeconfig", "Effect": "Allow", "Action": "eks:DescribeCluster",
      "Resource": "arn:aws:eks:us-east-1:${ACCOUNT_ID}:cluster/smart-tutor-*" },
    { "Sid": "ReadStackOutputs", "Effect": "Allow", "Action": "cloudformation:DescribeStacks",
      "Resource": "arn:aws:cloudformation:us-east-1:${ACCOUNT_ID}:stack/SmartTutor-prod-*/*" }
  ]
}
EOF

aws iam put-role-policy \
  --role-name smart-tutor-github-deploy \
  --policy-name deploy \
  --policy-document file://.aws-setup/deploy-policy.json

aws iam get-role --role-name smart-tutor-github-deploy --query Role.Arn --output text   # record this ARN
```

If #59 finds a missing permission, add it to this inline policy with a specific resource, never `*` on a service, and update this file.

## 4. GitHub environment `pilot` (about 5 min, needs repo admin)

Create the environment and allow deployments from `main` only:

```bash
gh api -X PUT repos/konica/agent-tutor/environments/pilot \
  -F "deployment_branch_policy[protected_branches]=false" \
  -F "deployment_branch_policy[custom_branch_policies]=true"

gh api -X POST repos/konica/agent-tutor/environments/pilot/deployment-branch-policies \
  -f name=main -f type=branch
```

Optional: in **Settings → Environments → pilot**, add **Required reviewers** if every deploy should wait for an approval.

Store the non-secret values the workflow needs as environment variables. There are no AWS keys to store, because OIDC replaces them.

```bash
gh variable set AWS_ROLE_ARN   --env pilot --body "arn:aws:iam::${ACCOUNT_ID}:role/smart-tutor-github-deploy"
gh variable set AWS_REGION     --env pilot --body us-east-1
gh variable set AWS_ACCOUNT_ID --env pilot --body "$ACCOUNT_ID"
gh variable list --env pilot
```

The deploy workflow in #59 declares `environment: pilot`, `permissions: id-token: write`, and calls `aws-actions/configure-aws-credentials` with `role-to-assume: ${{ vars.AWS_ROLE_ARN }}`. Nothing in this step can be tested end to end before #59, but a wrong `sub` or a missing environment shows up there as `Not authorized to perform sts:AssumeRoleWithWebIdentity`.

## 5. Decide the budget and the alert email (decision, about 5 min)

The idle cost is about **$250–300 a month**: EKS control plane, 2 nodes, NAT gateway, RDS, internal load balancer, CloudFront. Bedrock costs come on top once the agent and worker are enabled.

Decide:

- **Monthly budget amount.** Suggested: **$400**, which covers idle cost plus light Bedrock use.
- **Alert recipients.** One or more email addresses, ideally a shared inbox rather than one person.
- **Thresholds.** Suggested: email at 80% of **actual** spend and at 100% of **forecasted** spend.

#56 creates the budget in `BudgetsStack` from these values. Budget emails go straight to the addresses, with no subscription to confirm. Optional: in **Billing → Cost Explorer**, enable Cost Explorer now, because it takes up to 24 hours to show data.

## 6. Confirm the service quotas (about 5 min, longer if an increase is needed)

The pilot needs one EKS cluster with a managed node group of 2 small nodes (2–4 vCPU each), one NAT gateway with one Elastic IP, and one new VPC. Node upgrades briefly add extra nodes, so plan for at least **16 vCPU**.

```bash
q() { aws service-quotas get-service-quota --service-code "$1" --quota-code "$2" \
        --query "Quota.[QuotaName,Value]" --output text; }
q ec2 L-1216C47A    # Running On-Demand Standard (A, C, D, H, I, M, R, T, Z) instances, in vCPUs; need >= 16
q ec2 L-0263D0A3    # EC2-VPC Elastic IPs; need 1 free
q vpc L-F678F1CE    # VPCs per Region; need 1 free
aws service-quotas list-service-quotas --service-code eks \
  --query "Quotas[?QuotaName=='Clusters' || QuotaName=='Managed node groups per cluster'].[QuotaName,Value]" --output text

# Current usage, to compare with the "free" requirements above
aws ec2 describe-vpcs --query "length(Vpcs)"
aws ec2 describe-addresses --query "length(Addresses)"
aws eks list-clusters --query "length(clusters)"
```

If the vCPU quota is below 16, request an increase. Approval usually takes minutes to a day.

```bash
aws service-quotas request-service-quota-increase --service-code ec2 --quota-code L-1216C47A --desired-value 16
aws service-quotas list-requested-service-quota-change-history --service-code ec2 \
  --query "RequestedQuotas[].[QuotaCode,DesiredValue,Status]" --output text
```

A brand-new account may also be "pending verification" for EC2. If launching nodes later fails with that message, open a support case.

## 7. Record the results on #55

Fill this in and post it, then tick the acceptance criteria on #55:

```bash
gh issue comment 55 --body-file - <<'EOF'
## AWS prerequisites — done

| Item | Value |
|---|---|
| Account ID | <ACCOUNT_ID> |
| Region | us-east-1 |
| CDK bootstrap | CDKToolkit stack, bootstrap version <N>, done <date> |
| Admin role for EKS access (#56) | arn:aws:iam::<ACCOUNT_ID>:role/aws-reserved/sso.amazonaws.com/AWSReservedSSO_AdministratorAccess_<hash> |
| GitHub deploy role | arn:aws:iam::<ACCOUNT_ID>:role/smart-tutor-github-deploy (trusts repo:konica/agent-tutor:environment:pilot) |
| GitHub environment | pilot, deployment branches: main; required reviewers: <yes/no>; vars AWS_ROLE_ARN, AWS_REGION, AWS_ACCOUNT_ID |
| Monthly budget | $<amount> |
| Budget alert email(s) | <address(es)> |
| Budget thresholds | 80% actual, 100% forecasted |
| EC2 on-demand vCPU quota | <value> (increase requested: <yes/no, case id>) |
| Elastic IPs / VPCs / EKS clusters | <quota> / <quota> / <quota>, in use <n> / <n> / <n> |

Steps followed: docs/runbooks/pilot-aws-prerequisites.md
EOF
```

The account ID isn't a secret, but don't post access keys, session tokens or passwords on the issue.

Clean up the scratch folder: `rm -rf .aws-setup`.

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
| #56 public web app | Review and merge the PR. Run the first `cdk deploy` and add-on install from your laptop with `AWS_PROFILE=smart-tutor-admin`, following the runbook the slice writes. Open the CloudFront address and check that the app shell loads and the load balancer has no public address. Check that the budget email address is right in the Budgets console. |
| #57 Keycloak | Get the Keycloak admin password from Secrets Manager (the secret name is in the #57 runbook) and sign in at `https://<id>.cloudfront.net/auth/admin`. Create the client's account: realm **smart-tutor** → **Users → Add user** → email, first and last name, **Email verified** on → **Create** → **Credentials → Set password** with **Temporary** on, so the client chooses their own password at first sign-in. To remove access, **disable** the user (Users → user → Enabled off); the PRD has no account-deletion function yet. Do the #57 demo: the new user signs in to `/auth/realms/smart-tutor/account`. |
| #58 sign-in end to end | Run or watch the demo against the public address: sign-in reaches the Library with the user's name; `GET /api/me` with the token gives 200; after sign-out the token gets 401; without a token, 401 with `WWW-Authenticate: Bearer`. Then send the client the address and username, and the temporary password **through a separate channel**. **The client has access from here.** |
| #59 deploy on merge | Merge the workflow PR. If you turned on required reviewers, approve the `pilot` deployment in the Actions run. Check that the first run's smoke test passes. Practice one rollback to the previous image tag, following the runbook. |

### Cost control while the pilot is idle

The environment costs about $250–300 a month even with no traffic. If the pilot pauses for weeks, tear it down with the `cdk destroy` steps in the #56 runbook. RDS needs a final snapshot, because documents and threads are never deleted (PRD lifecycle invariant). The prerequisites in this file (bootstrap, OIDC role, GitHub environment) can stay. They cost nothing.
