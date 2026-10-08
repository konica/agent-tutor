# Pilot deploy (#56, #57, #58)

Deploys the pilot's infrastructure and the `web`, `keycloak`, and `api` charts, so the CloudFront address serves the app shell, Keycloak at `/auth` on RDS, and the API at `/api` (PRD §9.12, ADRs 0009 and 0010). It needs an account admin. Do [`pilot-aws-prerequisites.md`](pilot-aws-prerequisites.md) (#55) first. The big picture is in [`pilot-environment-overview.md`](pilot-environment-overview.md).

Commands are for **PowerShell 7** (`pwsh`). Run them from the repository root with your admin profile.

## 1. Before you start

- #55 is done: CDK bootstrap, the `SmartTutor-prod-GitHubDeploy` stack, and the GitHub environment exist.
- Tools: Node 22+, uv, AWS CLI v2, kubectl, helm, Docker (see the table in the prerequisites file).
- Set up the shell so it talks to real AWS. A terminal that loaded `.env` sends calls to LocalStack, and access-key variables override the profile:

```powershell
Get-ChildItem Env: | Where-Object Name -like "AWS_ENDPOINT_URL*" | ForEach-Object { Remove-Item "Env:$($_.Name)" }
Remove-Item Env:AWS_ACCESS_KEY_ID, Env:AWS_SECRET_ACCESS_KEY, Env:AWS_SESSION_TOKEN -ErrorAction SilentlyContinue
$env:AWS_IGNORE_CONFIGURED_ENDPOINT_URLS = "true"
$env:AWS_PROFILE = "default"          # your admin profile
$env:AWS_REGION = "us-east-1"
$env:JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = "1"
aws sts get-caller-identity
```

- The profile must resolve to a principal listed in `smart-tutor:eks-admin-principal-arns` in `infra/cdk.json` (pilot: `arn:aws:iam::685394474162:user/poweruser`). The cluster creator gets no admin access, so any other principal gets `Unauthorized` from kubectl and helm. Check the `Arn` that `aws sts get-caller-identity` prints.

## 2. Deploy the stacks (about 35 min; EKS is most of it, RDS adds about 10)

```powershell
Push-Location infra
uv sync
npx aws-cdk@latest diff
npx aws-cdk@latest deploy --all --require-approval broadening
Pop-Location
```

`--all` orders the stacks by their dependencies (the Cluster stack waits for `SmartTutor-prod-GitHubDeploy`, which already exists). Read the outputs you need:

```powershell
function Get-Output($Stack, $Key) {
    aws cloudformation describe-stacks --stack-name "SmartTutor-prod-$Stack" --query "Stacks[0].Outputs[?OutputKey=='$Key'].OutputValue" --output text
}
$VpcId = Get-Output Network VpcId
$Registry = Get-Output Registry RegistryUri
$Url = Get-Output Edge CloudFrontUrl
$VpcId; $Registry; $Url
```

## 3. Connect kubectl

```powershell
aws eks update-kubeconfig --name smart-tutor-prod --region us-east-1
kubectl get nodes        # 2 nodes, both Ready
```

Your admin principal and the deploy role have cluster-admin access entries; no other principal does. If kubectl says `Unauthorized`, run `aws sts get-caller-identity` and compare the `Arn` with `smart-tutor:eks-admin-principal-arns` in `infra/cdk.json`.

## 4. Install the add-ons

Versions are pinned. The values files are in `deploy/helm/addons/`.

```powershell
helm repo add eks https://aws.github.io/eks-charts
helm repo add external-secrets https://charts.external-secrets.io
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo update
helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller --version 3.5.0 -n kube-system -f deploy/helm/addons/aws-load-balancer-controller.yaml --set vpcId=$VpcId --wait
helm upgrade --install external-secrets external-secrets/external-secrets --version 2.11.0 -n external-secrets --create-namespace -f deploy/helm/addons/external-secrets.yaml --wait
helm upgrade --install metrics-server metrics-server/metrics-server --version 3.14.0 -n kube-system -f deploy/helm/addons/metrics-server.yaml --wait
```

## 5. Build and push the images

The nodes are x86_64, so build `linux/amd64`. On Apple silicon add `--platform linux/amd64`.

```powershell
$Tag = git rev-parse --short=12 HEAD
aws ecr get-login-password | docker login --username AWS --password-stdin $Registry
docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$Registry/smart-tutor/web:$Tag" web
docker push "$Registry/smart-tutor/web:$Tag"
docker build -t "$Registry/smart-tutor/keycloak:$Tag" deploy/keycloak
docker push "$Registry/smart-tutor/keycloak:$Tag"
docker build --target api -t "$Registry/smart-tutor/api:$Tag" backend
docker push "$Registry/smart-tutor/api:$Tag"
```

`/api` and `/auth` are relative, so the web image does not depend on the CloudFront address. The Keycloak image is optimized once at build time (ADR 0010).

## 6. Install the app

```powershell
helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace -f deploy/helm/smart-tutor/values-prod.yaml --set global.imageRegistry=$Registry --set global.imageTag=$Tag --set global.publicUrl=$Url --wait --timeout 15m
```

`global.publicUrl` is the CloudFront address from step 2. Without it Keycloak refuses to start. The first install runs the `db-bootstrap` hook, which creates the database roles and databases. Keycloak's first start takes about 2 min (schema and realm import), so `--wait` is slow the first time; `--timeout 15m` (Helm's default is 5 min) covers the hook plus that first start. Before the API rolls out, the `migrate` hook brings the app database to the latest Alembic revision; if it fails, the release fails and the running API stays.

## 7. Check

A new distribution and new targets can take a few minutes to settle. A 502 or 503 at first is expected: retry after 2 to 3 minutes.

```powershell
kubectl -n smart-tutor get pods,externalsecrets,targetgroupbindings
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-web --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-keycloak --query "TargetGroups[0].TargetGroupArn" --output text)
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-api --query "TargetGroups[0].TargetGroupArn" --output text)
curl.exe -sI $Url
curl.exe -sI ($Url -replace '^https','http')
$d = curl.exe -s "$Url/auth/realms/smart-tutor/.well-known/openid-configuration" | ConvertFrom-Json; $d.issuer; $d.token_endpoint; $d.jwks_uri
aws rds describe-db-instances --db-instance-identifier smart-tutor-prod --query "DBInstances[0].PubliclyAccessible"
```

- The pods are `Running`, the ExternalSecrets show `SecretSynced`, and the `TargetGroupBinding` objects exist.
- Target health shows 2 healthy web targets and healthy Keycloak targets, and 2 healthy API targets.
- The HTTPS request returns 200; the HTTP request returns 301 to HTTPS.
- The OpenID configuration shows `issuer` `<Url>/auth/realms/smart-tutor`, with your CloudFront address as `<Url>`, and `token_endpoint` and `jwks_uri` also start with `$Url/auth/`. An internal ALB name there means CloudFront is not forwarding the viewer Host (ADR 0010).
- The database is private: the RDS query prints `False`.
- Open `$Url` in a browser: the app shell loads.
- The API answers through CloudFront:

```powershell
curl.exe -si "$Url/api/me"          # 401, WWW-Authenticate: Bearer
curl.exe -s "$Url/api/healthz"      # {"status":"ok"}
```

- The ALB is not public:

```powershell
aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].Scheme" --output text   # internal
$Alb = aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].DNSName" --output text
Resolve-DnsName $Alb                                                                                       # only 10.40.x.x addresses
```

- Check the budget in **Billing → Budgets → smart-tutor-prod-monthly** (the amount in `smart-tutor:budget-monthly-usd`, emails at 80% actual and 100% forecasted). Delete the old $20 budget if it is still there (#55 follow-up).

## 8. Manage client accounts

Keycloak has no self-registration yet (#47), so you create each client's account.

1. Get the admin password. Do not paste it anywhere:

```powershell
aws secretsmanager get-secret-value --secret-id smart-tutor/keycloak/admin --query SecretString --output text
```

2. Sign in at `$Url/auth/admin` as `admin`. Keycloak shows a banner for the temporary admin. Optionally create a permanent admin user in realm **master** with the role `admin`, sign in as that user, and delete the bootstrap one.
3. Create the account: realm **smart-tutor** → **Users → Add user** → email, first and last name, **Email verified** on → **Create** → **Credentials → Set password** with **Temporary** on. Use at least 12 characters, and not the email address.
4. Demo (#57): open `$Url/auth/realms/smart-tutor/account` in a private window and sign in as the new user. Keycloak asks for a new password, then shows the account console. In DevTools → Application → Cookies for the CloudFront address, `KEYCLOAK_IDENTITY` and `KEYCLOAK_SESSION` show **Secure**: this proves CloudFront's `Forwarded: proto=https` reaches Keycloak (ADR 0010).
5. To remove access: **Users →** the user → **Enabled** off. Sessions end. The PRD has no account deletion.

Send the client the address, username, and temporary password through separate channels, after the demo below passes.

### Demo: a learner signs in (#58)

Use the account from step 8. Never paste a token anywhere except the variable below.

1. Open `$Url` in a private window and choose **Sign in**. Sign in as the step 8 account. The Library shows, with the user's name in the user menu.
2. In DevTools → Network, find the request to `/api/me` and copy the `Authorization` value after `Bearer `. In PowerShell:

```powershell
$Tok = "<paste>"
curl.exe -s -o NUL -w "%{http_code}" -H "Authorization: Bearer $Tok" "$Url/api/me"      # 200
```

3. Sign out in the app and run the same `curl.exe` again: `401`.
4. Call without a token: `401` with `WWW-Authenticate: Bearer`.

```powershell
curl.exe -si "$Url/api/me"
```

5. Restart Keycloak. While it rolls out, `/api/healthz` stays `200` and a call with a token gives `401`, never 5xx. After the rollout, signing in again works.

```powershell
kubectl -n smart-tutor rollout restart deploy/keycloak
curl.exe -s -o NUL -w "%{http_code}" "$Url/api/healthz"      # 200
```

6. DevTools shows no `OPTIONS` preflight to `/api`, because the app and the API share one origin.

## 9. Update after a change

Deploy infrastructure changes with CDK first (`npx aws-cdk@latest deploy --all` from `infra/`), then rebuild and push the images with a new tag and run the `helm upgrade` from step 6 again (with `--timeout 15m`). The order matters: the API pods read their SSM parameters at startup through a Pod Identity association that the CDK stacks create. The upgrade runs the `db-bootstrap` and `migrate` hooks first, so a password rotated in Secrets Manager reaches the database. Running Keycloak pods keep the old `KC_DB_PASSWORD` (the environment is read at start, and External Secrets refreshes `keycloak-db` only hourly), so after rotating: run the `helm upgrade`, force the sync with `kubectl -n smart-tutor annotate externalsecret keycloak-db force-sync=$(Get-Date -UFormat %s) --overwrite`, then `kubectl -n smart-tutor rollout restart deploy/keycloak`. #59 automates both.

## 10. Tear down

This keeps the #55 prerequisites, which cost nothing. `SmartTutor-prod-Data` keeps a final RDS snapshot, because documents and threads are never deleted. First note the VPC ID, which you need if the `Network` destroy fails (see below):

```powershell
$VpcId = Get-Output Network VpcId
```

Uninstall the app first, so the controller deregisters targets and removes its finalizers:

```powershell
helm uninstall smart-tutor -n smart-tutor --wait
helm uninstall aws-load-balancer-controller -n kube-system
helm uninstall external-secrets -n external-secrets
helm uninstall metrics-server -n kube-system
Push-Location infra
npx aws-cdk@latest destroy SmartTutor-prod-Edge SmartTutor-prod-Cluster SmartTutor-prod-Registry SmartTutor-prod-Budgets SmartTutor-prod-Data SmartTutor-prod-Storage SmartTutor-prod-Config SmartTutor-prod-Network
Pop-Location
```

Never use `--all` here: it would delete the GitHub deploy role. CloudFront takes about 15 min to disable and delete. If `Network` fails because the VPC origin's network interfaces are still being released, wait 10 minutes and run the destroy for `SmartTutor-prod-Network` again.

If it still fails, CloudFront may have left its `CloudFront-VPCOrigins-Service-SG` security group in the VPC. Find and delete it, then run the `Network` destroy again:

```powershell
$Sg = aws ec2 describe-security-groups --filters "Name=vpc-id,Values=$VpcId" "Name=group-name,Values=CloudFront-VPCOrigins-Service-SG" --query "SecurityGroups[0].GroupId" --output text
aws ec2 delete-security-group --group-id $Sg
```

ECR images are deleted with their repositories. List the final snapshot:

```powershell
aws rds describe-db-snapshots --db-instance-identifier smart-tutor-prod
```

Delete old snapshots you don't need, because they cost storage. A fresh deploy starts with an empty database. Restoring a snapshot is a manual step outside this runbook. Secrets in the CDK stacks are deleted at once (CloudFormation force-deletes them with no recovery window), so a redeploy with the same names works.

## 11. Costs

About **$250–300 a month** while idle, including RDS (`db.t3.micro` with 20 GiB, about $15 a month). During the testing phase the budget is **$20 a month** (`smart-tutor:budget-monthly-usd` in `infra/cdk.json`), with alerts. That is below the idle cost, so expect the 80% alert email within the first days the environment runs. Raise the value and run `npx aws-cdk@latest deploy SmartTutor-prod-Budgets` from `infra/` when the pilot starts.
