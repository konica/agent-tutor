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
