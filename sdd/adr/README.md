# Architecture decision records

One file per decision: `NNNN-short-title.md` (e.g. `0001-modular-monolith.md`). Never edit an accepted ADR; supersede it with a new one.

```markdown
# NNNN. Title

- Status: proposed | accepted | superseded by NNNN
- Date: YYYY-MM-DD

## Context
## Decision
## Consequences
```

Product decisions are recorded in `sdd/prd.md` (§6, §13); ADRs cover architecture.

| ADR | Decision |
|---|---|
| [0001](0001-modular-monolith.md) | Modular monolith with enforced import contracts |
| [0002](0002-content-document-split-sha256-dedupe.md) | Separate contents from documents; deduplicate by SHA-256 |
| [0003](0003-shared-subject-catalog.md) | Shared subject catalog with stable ids and personal names |
| [0004](0004-subjects-module.md) | Split the subject catalog out of `knowledge` into `subjects` |
| [0005](0005-pypdf-page-text-instead-of-docling.md) | Extract PDF page text with `pypdf` instead of Docling in Release 1 |
| [0006](0006-langchain-model-interfaces.md) | LangChain model interfaces as the model ports; `init_chat_model` builds them |
| [0007](0007-forward-learner-jwt-via-runtime-context.md) | Forward the learner JWT through LangGraph runtime context; Keycloak validates it on every hop (introspection) |
| [0008](0008-chunk-page-text-with-a-langchain-transformer.md) | Chunk page text with `RecursiveCharacterTextSplitter` (1,000 characters, overlap 200, one page per chunk) behind a LangChain document transformer |
| [0009](0009-serve-the-pilot-from-the-cloudfront-domain.md) | Serve the pilot from the CloudFront domain with path routing, through a VPC origin to an internal ALB |
| [0010](0010-keycloak-behind-cloudfront.md) | Keycloak behind CloudFront: pinned hostname, a trusted Forwarded header, databases made by a Helm hook |
| [0011](0011-per-learner-contents.md) | Per-learner contents: no cross-user deduplication; owners can delete (supersedes the cross-user parts of 0002) |
| [0012](0012-on-premise-default-deployment-mode.md) | On-premise (Docker Compose on one EC2 VM, Caddy, DuckDNS) is the default deployment mode; native-cloud (EKS) is opt-in (narrows 0009 and 0010 to native-cloud) |
| [0013](0013-secrets-stay-in-aws-secrets-manager.md) | Secrets stay in AWS Secrets Manager (no SOPS for now); no credential-shaped strings in the repository; GitGuardian findings are triaged, not silenced (proposed) |
| [0014](0014-on-premise-worker-egress-proxy.md) | On-premise worker egress: an internal Compose network whose only way out is an allowlisting Squid proxy (narrows 0012's egress gap: no internet) |
| [0015](0015-conversation-history-in-tutoring-table.md) | Conversation history in a tutoring-owned `thread_turns` table, written by the API; no LangGraph checkpointer |
| [0016](0016-deployment-modes-share-no-stack.md) | Deployment modes share no stack: each has its own ECR repositories; only the CDK bootstrap and the GitHub OIDC provider (native-cloud's GitHubDeploy owns it) are shared (supersedes 0012's "ECR is shared") |
| [0017](0017-self-hosted-phoenix-for-runtime-tracing.md) | Runtime traces and ratings go to self-hosted Arize Phoenix: one on the on-premise host for production, one in the local Compose stack for development; evals stay on LangSmith (supersedes 0014's LangSmith amendment); superseded by 0021 and 0023 |
| [0018](0018-guardrail-layering.md) | Guardrail layering: code checks, Guardrails AI output validation in process behind a `tutoring` `Guard` port, and an optional Bedrock Guardrails question screen; NeMo Guardrails rejected for Release 1 |
| [0019](0019-question-screen-fails-open.md) | The question screen is optional and fails open (the output guard fails closed); Bedrock at LOW measured at 0% false positives, but its p95 latency misses 300 ms; on in both modes since 2026-10-14, accepting the latency; the local DetectJailbreak screen (#200) is not eligible and ships only as an optional extra |
| [0020](0020-off-topic-questions-local-setfit-classifier.md) | Off-topic questions are screened before search by a local SetFit classifier (int8 ONNX, agent only) behind a `tutoring` `TopicClassifier` port; it fails open and stays off until the `topic_check` eval passes (supersedes PRD D5's "search always runs first") |
| [0021](0021-langfuse-on-a-shared-host.md) | Langfuse manages observability and evaluation (traces, ratings, annotation queues, datasets, experiments), self-hosted on a shared t3.xlarge in its own CDK project `platform/langfuse` (supersedes 0017's choice of Phoenix and its "evals stay on LangSmith") |
| [0022](0022-on-premise-off-hours-and-no-alarms.md) | On-premise hosts run 07:00–18:00 Asia/Ho_Chi_Minh (EventBridge Scheduler stops them at 18:00 and 00:00, starts at 07:00; anyone may start one by hand) and carry no CloudWatch alarms (supersedes #151's and #152's alarms) |
| [0023](0023-how-smart-tutor-uses-langfuse.md) | How Smart Tutor uses Langfuse: OpenTelemetry/OpenInference export to its OTLP endpoint (trace id = run id; learner hash as the user, thread as the session); projects `smart-tutor-on-premise`, `smart-tutor-local`, `smart-tutor-evals` in a Smart Tutor organization; a daily deletion job of ours for D25 (retention is Enterprise-only); CI evals fail fast while the host is off; ratings as `learner_rating` BOOLEAN scores (supersedes what remains of 0017) |
| [0024](0024-ci-evals-role-is-its-own-stack.md) | The CI evals role is the stack SmartTutor-EvalsCI, outside both deployment modes, with its own CDK entry and Make targets; its Bedrock policy comes from models.py (replaces #226's hand-made role and policy JSON) |
