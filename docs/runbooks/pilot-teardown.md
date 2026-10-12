# Pilot teardown (#177)

Stops the native-cloud pilot (`SmartTutor-prod-*`) from costing money. It needs an account admin whose principal is in `smart-tutor:eks-admin-principals` in `infra/cdk.json`. Whether to tear down is the product owner's decision (#156); this runbook only says how. The pilot was torn down on 2026-10-11 with `-DeleteDatabaseSnapshots -DeleteDocumentsBucket -DeleteLogGroups`, so a redeploy (section 8) starts from scratch.

Commands are for **PowerShell 7** (`pwsh`). Run them from the repository root. The script ignores LocalStack endpoints and access keys from your terminal (like `pilot-aws-prerequisites.ps1`), so it always talks to real AWS.

## 1. When to use it

The idle pilot costs about **$270-275 a month**: EKS $73, two `t3.large` nodes $121, NAT about $37, the internal ALB about $20, RDS about $15.5, node EBS $5, secrets $2.4 (#54). Tear it down when nobody uses it and the money matters. Redeploying takes about 35 min (section 8), and learners' documents and database survive unless you ask for their deletion.

## 2. What is deleted, kept, and why

| | Stacks | Why |
|---|---|---|
| Deleted | `Storage`, `Edge`, `Data`, `Cluster`, `Config`, `Registry`, `Network` | They hold the cost; the `Registry` holds only images, which the next build recreates. Storage goes before Edge because it imports Edge's CloudFront URL. |
| Kept | `Budgets` | The budget `smart-tutor-prod-monthly` is free. `-DeleteBudget` deletes it. |
| Kept | `GitHubDeploy` | It owns the account's GitHub OIDC provider, which on-premise's deploy role imports: the one resource the two modes share (ADR 0016). IAM only, free. |
| Kept | `CDKToolkit` and the GitHub environment `native-cloud` | The bootstrap is the account's, and both modes deploy with it; the environment lets the pilot be redeployed. |

On-premise keeps running. The script deletes only native-cloud's names: the stacks `SmartTutor-prod-*`, the secrets `smart-tutor/...`, the log groups of `smart-tutor-prod`, the snapshots of the `smart-tutor-prod` database, and the bucket `smart-tutor-documents-<account>`. Nothing it deletes starts with `SmartTutor-OnPremise-` or `smart-tutor-on-premise`. To tear down on-premise instead, see [`on-premise-deploy.md`](on-premise-deploy.md) §8.

The script also removes what Kubernetes created outside CloudFormation: the `smart-tutor` release and its TargetGroupBindings, then the AWS Load Balancer Controller, External Secrets, and metrics-server. If those stayed, their security-group rules and ENIs would block the Edge and Network deletes. Before Network it deletes unattached VPC-CNI ENIs of the cluster and waits for CloudFront to release its VPC-origin ENIs (up to 45 min), then deletes `CloudFront-VPCOrigins-Service-SG`. All of this is scoped to the pilot's VPC.

It runs one `cdk destroy --exclusively <stack>` per stack. Every native-cloud stack depends on Network, so without `--exclusively` a destroy of Network would also destroy every stack that depends on it.

## 3. Stop auto-deploys first

Since #150 native-cloud deploys on a merge only while `NATIVE_CLOUD_AUTO_DEPLOY` is `true`. Make sure it isn't (the script checks it and stops if it is `true`; it never changes it itself):

```powershell
gh variable delete NATIVE_CLOUD_AUTO_DEPLOY --repo konica/agent-tutor   # or set it to false
```

## 4. Dry run

```powershell
./docs/runbooks/pilot-teardown.ps1 -AwsProfile default -DryRun
```

It only reads. It prints the stacks it would delete, each stack it keeps with the reason, each step it would run, and the leftovers (snapshots, bucket, log groups, secrets). It never prompts, and only warns about the variable.

## 5. Real run (about 25 to 60 min)

```powershell
./docs/runbooks/pilot-teardown.ps1 -AwsProfile default
```

It asks you to type the account id, then runs the Kubernetes cleanup, the stack destroys, and the leftovers report. CloudFront alone takes about 15 min to disable and delete, and its ENIs can take longer to release. Add `-Force` to skip the prompts (unattended runs). At the end it warns if an EKS cluster, the ALB, or a NAT gateway is still there.

## 6. Switches

Nothing below is deleted unless you pass the switch. The irreversible ones each ask for their own typed confirmation (skipped by `-Force`):

| Switch | Deletes | Notes |
|---|---|---|
| `-DeleteBudget` | The `SmartTutor-prod-Budgets` stack | Free to keep; no confirmation. |
| `-DeleteDatabaseSnapshots` | RDS manual and final snapshots of `smart-tutor-prod*` | The final snapshot is the only copy of the database (documents, threads, Keycloak users). About $0.095 per GiB-month. |
| `-DeleteDocumentsBucket` | `smart-tutor-documents-<account>`: every object version and delete marker, then the bucket | Learner PDFs. `aws s3 rm --recursive` would leave the versions, which is why the script does it. |
| `-DeleteLogGroups` | Log groups `/aws/eks/smart-tutor-prod*`, `/aws/rds/instance/smart-tutor-prod*`, `/aws/lambda/SmartTutor-prod-*` | CloudWatch logs never expire on their own. |

You can run the script again later with only a switch once you have decided. Secrets from the stacks are checked by their exact names; any left pending deletion are force-deleted so a redeploy can create them again.

## 7. What is left and what it costs

Under **$2 a month**: the bootstrap bucket, the RDS final snapshot (about $2 for 20 GiB), and the documents bucket. The script prints the leftovers at the end of each run.

## 8. Redeploy later

1. Deal with the documents bucket if you kept it. Its name is fixed and it is retained, so creating the Storage stack fails with "already exists". Either bring it into the stack with `cdk import`, or delete it first with `-DeleteDocumentsBucket`. Its CORS rule must name the new CloudFront domain; the Storage stack sets it, so after an import redeploy Storage and check `aws s3api get-bucket-cors`.
2. The image build deploys `Registry` before it pushes, so a redeploy recreates the repositories (they come back empty). Follow [`pilot-deploy.md`](pilot-deploy.md) from step 2. Or run **deploy** by hand with mode `native-cloud`, or set `NATIVE_CLOUD_AUTO_DEPLOY` to `true` and merge; it needs the kept `GitHubDeploy` role, the bootstrap, and the `native-cloud` environment.

- A fresh deploy starts with an **empty database**. To restore the final snapshot instead, restore it to a new instance with the same identifier, then fix the credentials: the stacks' secrets were deleted, so the new ones don't match the restored database. Set the master password with `aws rds modify-db-instance --db-instance-identifier smart-tutor-prod --master-user-password <the new smart-tutor/rds/master secret> --apply-immediately`, and run `ALTER ROLE ... PASSWORD ...` for the app and keycloak roles with the new `smart-tutor/db/app` and `smart-tutor/db/keycloak` secrets. This is manual and outside these runbooks.
- `rollback.yml` does not work while the pilot is down: it has no infrastructure to roll back onto.

## 9. Troubleshooting

The script is safe to run again: it skips what is gone and retries stacks in `DELETE_FAILED`.

- **`Unauthorized` from kubectl or helm.** Your principal is not in `smart-tutor:eks-admin-principals`. Use the right profile.
- **Edge or Network is `DELETE_FAILED`.** An ENI or a security-group rule is still attached, or the Kubernetes cleanup was skipped. Wait and run the script again. Look at the stack's **Events** in the CloudFormation console, or list what uses the VPC: `aws ec2 describe-network-interfaces --filters "Name=vpc-id,Values=<vpc id>"`.
- **TargetGroupBindings remain after 10 min.** The controller could not deregister targets, often because it was already uninstalled. Remove the finalizers: `kubectl patch targetgroupbinding <name> -n smart-tutor --type merge -p '{"metadata":{"finalizers":null}}'`, then rerun.
- **Network is `DELETE_FAILED` on a security group named `eks-cluster-sg-smart-tutor-prod-*`.** EKS sometimes leaves its cluster security group behind. Delete it once no network interface uses it (`aws ec2 delete-security-group --group-id <id>`), then rerun.
- **A stack is `DELETE_FAILED` on a non-empty resource.** Read the event reason, fix it by hand, rerun.
