# Pilot deploy: the public web app (#56)

Deploys the pilot's infrastructure and the `web` chart, so the CloudFront address serves the app shell (PRD §9.12, ADR 0009). It needs an account admin. Do [`pilot-aws-prerequisites.md`](pilot-aws-prerequisites.md) (#55) first. The big picture is in [`pilot-environment-overview.md`](pilot-environment-overview.md).

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

## 2. Deploy the stacks (about 25 min; EKS is most of it)

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

Your admin principal and the deploy role have cluster-admin access entries; no other principal does.

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

## 5. Build and push the web image

The nodes are x86_64, so build `linux/amd64`. On Apple silicon add `--platform linux/amd64`.

```powershell
$Tag = git rev-parse --short=12 HEAD
aws ecr get-login-password | docker login --username AWS --password-stdin $Registry
docker build --build-arg VITE_API_URL=/api --build-arg VITE_KEYCLOAK_URL=/auth -t "$Registry/smart-tutor/web:$Tag" web
docker push "$Registry/smart-tutor/web:$Tag"
```

`/api` and `/auth` are relative, so the image does not depend on the CloudFront address.

## 6. Install the app

```powershell
helm upgrade --install smart-tutor deploy/helm/smart-tutor -n smart-tutor --create-namespace -f deploy/helm/smart-tutor/values-prod.yaml --set global.imageRegistry=$Registry --set global.imageTag=$Tag --wait
```

## 7. Check

```powershell
kubectl -n smart-tutor get pods,targetgroupbindings
aws elbv2 describe-target-health --target-group-arn (aws elbv2 describe-target-groups --names smart-tutor-prod-web --query "TargetGroups[0].TargetGroupArn" --output text)
curl.exe -sI $Url
curl.exe -sI ($Url -replace '^https','http')
```

- The pods are `Running`, and the `TargetGroupBinding` exists.
- Target health shows 2 healthy targets.
- The HTTPS request returns 200; the HTTP request returns 301 to HTTPS.
- Open `$Url` in a browser: the app shell loads. Sign-in fails until #57 and #58. That is expected.
- The ALB is not public:

```powershell
aws elbv2 describe-load-balancers --names smart-tutor-prod --query "LoadBalancers[0].[Scheme,DNSName]"   # internal
Resolve-DnsName <DNSName>                                                                              # only 10.40.x.x addresses
```

- Check the budget in **Billing → Budgets → smart-tutor-prod-monthly** (USD 400, emails at 80% actual and 100% forecasted). Delete the old $20 budget if it is still there (#55 follow-up).

## 8. Update after a change

Rebuild and push the image with a new tag, then run the `helm upgrade` from step 6 again. For infrastructure changes, run `npx aws-cdk@latest deploy --all` from `infra/`. #59 automates both.

## 9. Tear down

This keeps the #55 prerequisites, which cost nothing. Uninstall the app first, so the controller deregisters targets and removes its finalizers:

```powershell
helm uninstall smart-tutor -n smart-tutor --wait
helm uninstall aws-load-balancer-controller -n kube-system
helm uninstall external-secrets -n external-secrets
helm uninstall metrics-server -n kube-system
Push-Location infra
npx aws-cdk@latest destroy SmartTutor-prod-Edge SmartTutor-prod-Cluster SmartTutor-prod-Registry SmartTutor-prod-Budgets SmartTutor-prod-Data SmartTutor-prod-Storage SmartTutor-prod-Config SmartTutor-prod-Network
Pop-Location
```

Never use `--all` here: it would delete the GitHub deploy role. CloudFront takes about 15 min to disable and delete. If `Network` fails because the VPC origin's network interfaces are still being released, wait 10 minutes and run the destroy for `SmartTutor-prod-Network` again. ECR images are deleted with their repositories. From #57 on, RDS keeps a final snapshot, and that slice adds the step.

## 10. Costs

About **$250–300 a month** while idle. The budget is **$400 a month**, with alerts.
