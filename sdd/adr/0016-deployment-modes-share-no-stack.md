# 0016. Deployment modes share no stack

- Status: accepted
- Date: 2026-10-11
- Supersedes: ADR 0012's "ECR is shared"

## Context

ADR 0012 gave each deployment mode its own bucket, queue, SSM parameters, secrets, and deploy role, but left ECR shared: the repositories `smart-tutor/<service>` belonged to native-cloud's `SmartTutor-prod-Registry` stack, on-premise pushed its images there, and the on-premise Host pulled them from there. Native-cloud's Registry could then never be torn down without breaking on-premise, and native-cloud's teardown had to keep it. The product owner and the cloud architect decided that the two modes must not share stacks (#206).

## Decision

- **Each mode has its own ECR repositories,** named after its data prefix: on-premise `smart-tutor-on-premise/<service>` in `SmartTutor-OnPremise-prod-Registry`; native-cloud keeps `smart-tutor/<service>` in `SmartTutor-prod-Registry`, the names the pilot was deployed with, so its Helm values don't change. Both use scan on push, keep the last 30 images, and delete their images on teardown.
- **Each mode's deploy role pushes only to its own repositories,** and the on-premise Host pulls only from on-premise's.
- **Every merge builds the images of each mode it deploys,** with that mode's role. A push that deploys both modes builds twice. Before its first push the build deploys its mode's `GitHubDeploy` and `Registry` stacks, so the repositories and the push permission exist; later builds find nothing to change.
- **A deploy or rollback looks only in its own mode's repositories.** It never falls back to the other mode's.
- **Shared, by exception:** the account's CDK bootstrap (`CDKToolkit`), and the GitHub OIDC provider. AWS allows one OIDC provider per URL in an account, so native-cloud's `GitHubDeploy` creates it and on-premise's `GitHubDeploy` imports it. Nothing else is shared.

## Alternatives rejected

- **Keep ECR shared.** Simple, but it ties on-premise's deploys to a native-cloud stack the product owner may want to tear down.
- **Rename native-cloud's repositories too** (for example `smart-tutor-native-cloud/*`). Symmetric, but it changes the pilot's Helm values and strands its existing images for no gain.
- **Copy images between the modes' repositories** instead of building per mode. One build, but one role would need to read the other mode's repositories, which is the coupling this decision removes.
- **A documented one-time `cdk deploy` before the first merge.** It works once, but a fresh account or a torn-down registry would need it again; the build deploying its own registry heals both.

## Consequences

- Native-cloud's teardown deletes its Registry too; a redeploy recreates it on the first build.
- A push with `NATIVE_CLOUD_AUTO_DEPLOY=true` builds the images twice.
- Commits merged before #206 have images only in `smart-tutor/*`. On-premise can't roll back to them unless their images are built into its repositories by hand (`docs/runbooks/on-premise-deploy.md`).
- The image build needs Node and uv and permission to deploy two stacks, which the deploy roles already had (through the CDK bootstrap roles).
