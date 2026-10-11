# 0012. On-premise is the default deployment mode; native-cloud is opt-in

- Status: accepted; "ECR is shared" superseded by 0016 (the modes share no stack)
- Date: 2026-10-09
- Supersedes: the parts of 0009 and 0010 listed under "What still holds from 0009 and 0010", which now apply only to native-cloud mode

## Context

The pilot runs on EKS, RDS, CloudFront, an internal ALB, and NAT (ADR 0009, 0010). For a pilot of up to 50 learners, the EKS control plane, RDS, the ALB, and the NAT gateway cost far more than the workload needs. Keeping the cluster, its add-ons, and the edge running is also more work than a small team should spend before the pilot proves itself.

The product does not need managed Kubernetes. Its services already run together in Docker Compose for local development. The product owner chose two named **deployment modes** (`CONTEXT.md`, grilling session 2026-10-09, #145):

- **On-premise mode**, the default. Our services run on one VM we operate, and S3, SQS, SSM, Secrets Manager, and ECR stay managed.
- **Native-cloud mode**, opt-in. Today's EKS deployment, on managed services end to end.

The product behaves the same in both modes.

## Decision

- **One CDK app, two modes.** It takes `-c smart-tutor:mode=on-premise|native-cloud` and defaults to `on-premise`. Each mode has its own bucket, queue, and SSM parameters, so the modes never share data. ECR was shared until ADR 0016 gave each mode its own repositories. On-premise adds a **Host** stack.
- **Host:** one **t3.large** EC2 instance (Amazon Linux 2023) with a 50 GB encrypted gp3 data volume. If it runs short, it grows to t3.xlarge, or a second data VM is added.
- **Runtime:** **Docker Compose** runs web, API, agent, MCP server, worker, Keycloak, **PostgreSQL + pgvector**, and **Caddy**. Scheduled jobs are systemd timers that call `docker compose run`.
- **Edge:** Caddy routes by path (`/` to web, `/api/*` to the API, `/auth/*` to Keycloak) and gets its certificate from Let's Encrypt automatically. The address is an Elastic IP with a **DuckDNS** subdomain, falling back to `<eip>.sslip.io`. There is no CloudFront distribution and no ALB.
- **Network:** a VPC of its own with one public subnet, **no NAT**, and an S3 gateway endpoint. The security group allows only 80 and 443 inbound. There is no SSH; operators use SSM Session Manager.
- **Delivery:** every push to `main` runs the checks, pushes images to ECR, runs `cdk deploy`, and then uses **SSM Run Command** to pull images, migrate, and run `docker compose up -d`. A smoke test follows. Brief downtime during a deploy is acceptable.
- **Native-cloud deploys only when chosen:** by `workflow_dispatch`, or automatically when the repository variable `NATIVE_CLOUD_AUTO_DEPLOY=true`. CI still runs `cdk synth` and `helm lint` for native-cloud, so it doesn't rot. The running pilot stays up, deployed only by hand, until on-premise passes its smoke test. Then the product owner decides what to do with it.
- **Worker isolation on the VM:** the worker runs as non-root with a read-only filesystem, `cap_drop: [ALL]`, CPU and memory limits, and a per-file timeout. It has no **egress allowlist** yet; that known gap has its own ticket and must land before "pilot starts" (M4).
- **Operations:** daily EBS snapshots kept 7 days, a nightly `pg_dump` to S3, a restore runbook, and one restore drill. Docker health checks and restart policies, log rotation, an EC2 status-check recovery alarm, an uptime check on `/api/healthz`, Budgets, and weekly SSM patching.
- **Data:** on-premise starts with an empty database. Nothing is migrated from the pilot.

### What still holds from 0009 and 0010

| ADR 0009 / 0010 part | On-premise | Native-cloud |
|---|---|---|
| One origin with path routing `/`, `/api/*`, `/auth/*`; the web image uses relative `/api` and `/auth` | Yes (Caddy) | Yes (CloudFront) |
| CloudFront domain, VPC origin, internal ALB owned by CDK, `TargetGroupBinding`, plain HTTP from CloudFront to the ALB | No | Yes |
| Keycloak's pinned hostname (`KC_HOSTNAME` = public URL with `/auth`) | Yes (the DuckDNS or sslip.io URL) | Yes |
| CloudFront adds `Forwarded: proto=https` and Keycloak reads `KC_PROXY_HEADERS=forwarded` | No. Caddy terminates TLS and sets `X-Forwarded-Proto` itself, so Keycloak trusts the headers Caddy sends (`KC_PROXY_HEADERS=xforwarded`) | Yes |
| `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true` (services reach Keycloak by its internal name) | Yes (the Compose service name) | Yes (the Kubernetes Service) |
| Optimized Keycloak image (`kc.sh build`, `start --optimized`) | Yes | Yes |
| RDS, plus a Helm hook Job that creates the `app` and `keycloak` databases and roles | No. PostgreSQL runs in a container, and an init script creates the databases and roles (as `local/postgres` does) | Yes |
| Realm imported once from a file with placeholders; client secrets from Secrets Manager | Yes | Yes |

## Alternatives rejected

- **k3s on the VM.** The VM bill is the same, but k3s uses more RAM, and running a cluster takes more work than Compose. Reusing the Helm chart doesn't make up for that.
- **RDS for on-premise.** It would cost more than the VM and need a private subnet to reach. PostgreSQL on the VM, with EBS snapshots and a nightly `pg_dump`, is enough for the pilot.
- **CloudFront or an ALB in front of the VM.** Either adds cost and a second hop. Caddy handles TLS and path routing on the VM, and DuckDNS gives a stable name without buying a domain.
- **A NAT gateway or a private subnet.** NAT is the largest fixed cost after EKS and RDS. A public subnet whose security group allows only 80 and 443 inbound needs neither.
- **Retiring native-cloud.** It stays as an opt-in mode for a later move to managed services, and CI keeps it buildable.

## Consequences

- **One VM is a single point of failure.** A host failure or a deploy takes the product down until the instance recovers. That is accepted for the pilot: the status-check alarm recovers the instance, and snapshots and dumps bound data loss to one day.
- **Worker egress gap.** Until the allowlist ticket lands, a malicious PDF that compromises the parser could reach the internet from the worker container. The other isolation measures apply. The gap blocks "pilot starts" (PRD §9.10).
- **Two deploy paths.** Infrastructure changes are made per mode. The product code, images, and Keycloak realm are the same in both.
- **Address changes.** Moving to a custom domain needs a DNS record for the Elastic IP, a new `KC_HOSTNAME`, and new Keycloak redirect URIs. Caddy obtains the certificate itself.
- **Local development is unchanged.**
