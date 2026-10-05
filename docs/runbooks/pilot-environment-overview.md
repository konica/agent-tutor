# Pilot environment on AWS: the big picture

How the pilot environment (#54) fits together across GitHub and AWS: who deploys what, how the pieces trust each other, and how a learner's request travels. It shows the **target** after #55–#59, per the decisions on #54 and PRD §9.11–§9.12. Today the CDK bootstrap and the deploy role exist (#55), and #56 adds the network, cluster, registry, edge (internal ALB and CloudFront), and budget stacks. The deploy steps are in [`pilot-deploy.md`](pilot-deploy.md). The human setup is in [`pilot-aws-prerequisites.md`](pilot-aws-prerequisites.md).

## 1. Platforms and trust

Nothing on GitHub holds an AWS key. A deploy job in the `pilot` environment gets a short-lived GitHub OIDC token. AWS STS swaps it for a one-hour session of the deploy role, and the role can only do the five things in its policy. CloudFormation, not the role, creates the infrastructure, through the CDK bootstrap roles.

```mermaid
flowchart TB
  subgraph GH["GitHub — konica/agent-tutor"]
    PR["Pull request"] -->|merge| MAIN["main branch"]
    MAIN -->|push event| WF["Actions workflow<br/>deploy (#59)"]
    WF -.->|"job runs in"| ENV["Environment pilot<br/>branches: main only<br/>vars: AWS_ROLE_ARN, AWS_REGION, AWS_ACCOUNT_ID"]
    WF -->|"id-token: write"| TOK["OIDC token<br/>sub = repo:konica@1114311/agent-tutor@1399048529:environment:pilot"]
  end

  subgraph AWS["AWS account 685394474162 — us-east-1"]
    subgraph IAM["IAM — stack SmartTutor-prod-GitHubDeploy + CDK bootstrap (#55)"]
      OIDC["OIDC provider<br/>token.actions.githubusercontent.com"]
      ROLE["Role smart-tutor-github-deploy<br/>trusts only that sub"]
      CDKR["CDK bootstrap roles<br/>cdk-hnb659fds-*"]
    end
    CFN["CloudFormation<br/>SmartTutor-prod-* stacks"]
    ECR["ECR<br/>smart-tutor/api, web, keycloak"]
    EKS["EKS cluster smart-tutor-prod"]
  end

  TOK -->|"AssumeRoleWithWebIdentity"| OIDC --> ROLE
  ROLE -->|"sts:AssumeRole"| CDKR -->|"cdk deploy"| CFN
  ROLE -->|"docker push"| ECR
  ROLE -->|"DescribeCluster + EKS access entry"| EKS
  CFN -->|creates and updates| EKS
  EKS -->|pulls images| ECR
```

### Setup order: AWS first, then GitHub

The only real dependency is that GitHub stores the role's ARN, so the role has to exist first. Trust is checked only when a deploy job signs in: the role trusts a subject string, so AWS doesn't need the GitHub environment when the role is created. The environment just has to exist before the first deploy. `pilot-aws-prerequisites.ps1` runs steps 0–4 in this order.

| # | Where | What | Needs |
|---|---|---|---|
| 0 | GitHub (read only) | Read the repository's OIDC subject prefix `repo:konica@1114311/agent-tutor@1399048529`; it must match `infra/cdk.json` | Nothing; GitHub fixes it for the repository |
| 1 | AWS | `cdk bootstrap` (`CDKToolkit` stack) | Admin credentials |
| 2 | AWS | Deploy `SmartTutor-prod-GitHubDeploy`: the OIDC provider, then the role that trusts `…:environment:pilot` | Step 1, and the prefix from step 0 |
| 3 | GitHub | Create the environment `pilot`, limited to `main` | Nothing (it can run before step 2) |
| 4 | GitHub | Set the variables `AWS_ROLE_ARN`, `AWS_REGION`, `AWS_ACCOUNT_ID` in `pilot` | The role ARN from step 2 |
| 5 | Both, from #59 on | A deploy job sends its token; AWS STS checks it against the role's trust and returns 1-hour credentials | Steps 2–4 |

```mermaid
sequenceDiagram
  actor A as Admin (script, once)
  participant GH as GitHub
  participant AWS as AWS account

  A->>GH: read OIDC subject prefix (step 0)
  GH-->>A: repo:konica@1114311/agent-tutor@1399048529
  A->>AWS: cdk bootstrap (step 1)
  A->>AWS: cdk deploy SmartTutor-prod-GitHubDeploy (step 2)
  AWS-->>A: role ARN (trusts ...:environment:pilot)
  A->>GH: create environment pilot, main only (step 3)
  A->>GH: set AWS_ROLE_ARN, AWS_REGION, AWS_ACCOUNT_ID (step 4)
  Note over GH,AWS: Later, on every merge to main (issue 59)
  GH->>AWS: deploy job in pilot sends its OIDC token (step 5)
  AWS-->>GH: token matches the role's trust, so 1-hour credentials
```

## 2. Production runtime

There's a single public entry point: the AWS-generated CloudFront address, served over HTTPS. CloudFront routes by path. It reaches an **internal** load balancer through a VPC origin, so nothing inside the VPC has a public address, and tokens never cross the internet unencrypted. Because the browser, API and Keycloak share one origin, the API needs no CORS.

```mermaid
flowchart LR
  U["Learner's browser"] -->|"HTTPS"| CF["CloudFront<br/>https://ID.cloudfront.net"]
  ADM["Admin's browser"] -->|"HTTPS /auth/admin"| CF

  subgraph VPC["VPC — private subnets"]
    ALB["Internal Application Load Balancer<br/>(CDK EdgeStack; pods registered by the LB controller)"]
    subgraph K8S["EKS — Helm chart smart-tutor"]
      WEB["web<br/>React app shell"]
      API["api<br/>FastAPI"]
      KC["keycloak<br/>realm smart-tutor"]
      MIG["migrate<br/>Helm hook Job"]
      ESO["External Secrets"]
      LATER["agent · mcp · worker<br/>disabled until their slices"]
    end
    RDS[("RDS PostgreSQL + pgvector<br/>DB app · DB keycloak")]
    NAT["NAT gateway"]
  end

  SM["Secrets Manager<br/>DB credentials, Keycloak admin,<br/>API client secret"]

  CF -->|"VPC origin"| ALB
  ALB -->|"/"| WEB
  ALB -->|"/api/*"| API
  ALB -->|"/auth/*"| KC
  API -->|"token introspection<br/>(in-cluster URL)"| KC
  API --> RDS
  MIG -->|"alembic upgrade"| RDS
  KC --> RDS
  SM -->|"Pod Identity"| ESO -->|"Kubernetes Secrets"| API & KC & MIG
  K8S -.->|"outbound only"| NAT
```

| Path | Service | Notes |
|---|---|---|
| `/` | web | Static app shell. Built with the API at `/api` and Keycloak at `/auth` on the same origin. |
| `/api/*` | api | Every call needs a valid bearer token; otherwise 401 with `WWW-Authenticate: Bearer`. |
| `/auth/*` | keycloak | Issuer `https://<id>.cloudfront.net/auth/realms/smart-tutor`. Self-registration is off until #47; the admin creates accounts. |

## 3. Sign-in and an API call

```mermaid
sequenceDiagram
  autonumber
  actor L as Learner
  participant CF as CloudFront
  participant W as web
  participant K as keycloak
  participant A as api
  participant DB as RDS

  L->>CF: GET /
  CF->>W: forward
  W-->>L: app shell
  L->>CF: GET /auth/realms/smart-tutor/... (login page)
  CF->>K: forward
  L->>K: username + password (via CloudFront)
  K->>DB: check user (DB keycloak)
  K-->>L: authorization code → tokens
  L->>CF: GET /api/me, Authorization: Bearer token
  CF->>A: forward
  A->>K: introspect token (in-cluster)
  K-->>A: active, user id, name
  A->>DB: read learner data (DB app)
  A-->>L: 200 {name, ...}
  Note over L,A: After sign-out, introspection says inactive, so the same token gets 401
```

## 4. Deploy on merge

Merging to `main` runs one deployment at a time:

```mermaid
sequenceDiagram
  autonumber
  actor D as Developer
  participant GH as GitHub Actions (env pilot)
  participant STS as AWS STS
  participant ECR as ECR
  participant CFN as CloudFormation (via CDK)
  participant EKS as EKS (helm)
  participant CF as CloudFront address

  D->>GH: merge PR into main
  GH->>GH: checks (ruff, mypy, import contracts, pytest, web build, infra tests)
  GH->>STS: OIDC token → AssumeRoleWithWebIdentity
  STS-->>GH: 1-hour credentials of smart-tutor-github-deploy
  GH->>ECR: push api, web, keycloak images tagged with the commit SHA
  GH->>CFN: cdk deploy (VPC, EKS, RDS, ECR, CloudFront, budget ...)
  GH->>EKS: helm upgrade --set global.imageTag=SHA
  EKS->>EKS: pre-upgrade hook: migrate Job (a failure stops the release)
  EKS->>EKS: roll out api, web, keycloak (readiness probes)
  GH->>CF: smoke test: web loads, /api/me without token is 401, issuer is right
  CF-->>GH: pass, or the run fails visibly
```

To roll back, run `helm upgrade` with an earlier commit SHA as the image tag (the #59 runbook).

## 5. Who builds which piece

| Piece | Built in | By | How |
|---|---|---|---|
| CDK bootstrap, OIDC provider, deploy role, GitHub environment `pilot`, quota checks, budget decision | #55 | Human (admin) runs one script, once | CDK `GitHubDeployStack`; `pilot-aws-prerequisites.ps1` for bootstrap and the GitHub environment |
| VPC, NAT, EKS + node group, Pod Identity, ECR, add-ons (load balancer controller, External Secrets, metrics-server), internal load balancer, CloudFront with VPC origin, `web`, budget alarm, ADR + PRD update | #56 | Agent; human runs the first deploy | CDK `NetworkStack`, `ClusterStack`, `RegistryStack`, `EdgeStack`, `BudgetsStack`; `deploy/helm/addons/`; chart `web` |
| RDS (DB app, DB keycloak), Secrets Manager entries, `keycloak` at `/auth`, production realm | #57 | Agent; human creates the client's account | CDK `DataStack`, `ConfigStack`; chart `keycloak` |
| `api` at `/api`, `migrate` hook Job, same-origin web build, probes | #58 | Agent; human runs the demo and hands over access | chart `api`, `values-prod.yaml` |
| Deploy-on-merge workflow, smoke test, rollback runbook | #59 | Agent; human merges and approves | `.github/workflows/` |
| S3 documents bucket, SQS, agent, MCP server, worker, Bedrock access | Later slices | — | `StorageStack`; charts stay disabled for now |

## Cost

About **$250–300 a month** while idle (EKS control plane, 2 nodes, NAT gateway, RDS, internal load balancer, CloudFront). The budget is **$400 a month**, with email alerts to the owner at 80% of actual and 100% of forecasted spend.
