---
type: quickstart
title: Smart Tutor — Quick Start
description: Entry point for developers and agents. Covers the product, the repository map, release scope, module layout, product invariants, OpenWiki retrieval tools, and routes every common task to the right wiki page.
tags: [quickstart, architecture, repository-map, onboarding, invariants]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-03T03:19:50.688Z
sources:
  - id: openwiki-source-8037e2358a2c4f9b2c722a11
    resource: repo://AGENTS.md
  - id: openwiki-source-410ab36600fefdde765cb24e
    resource: repo://backend/AGENTS.md
  - id: openwiki-source-23775c3de52f3ab95a13cb8b
    resource: repo://README.md
  - id: openwiki-source-473ea646d59721d67fc55bbb
    resource: repo://sdd/prd.md
generated: { by: "openwiki/0.7.0", at: "2026-10-03T03:19:50.688Z" }
---

# Smart Tutor — Quick Start

Smart Tutor is an AI tutor that answers questions **only from the learner's own PDFs**, with citations. Learners upload documents into a private library; each document is assigned 1–3 subjects drawn from a **shared subject catalog** visible to all users. When a learner asks a question the tutor auto-detects which of their subjects the conversation belongs to and retrieves chunks exclusively from documents in those subjects — never from another learner's data. Identical files are deduplicated by **SHA-256** across all users: a file is extracted, chunked, and embedded exactly once regardless of how many learners upload it. The system is designed around an explicit agent development lifecycle (tracing, evaluation, security hardening, and production deployment on AWS) so the agent is demonstrably reliable and safe.

---

## Sources of truth

OpenWiki pages are a **generated view** — they are synthesized from the authoritative sources below. When the two disagree, the source files win. Do not hand-edit OpenWiki pages; update the source and let OpenWiki regenerate.

| Need | File |
|---|---|
| Product behavior, user stories, data model, flows, evals, roadmap | [`sdd/prd.md`](../sdd/prd.md) (v2.2) |
| Folder structure, module boundaries, import rules | [`sdd/specs/2026-10-02-project-structure-design.md`](../sdd/specs/2026-10-02-project-structure-design.md) |
| Architecture decisions and rationale | [`sdd/adr/`](../sdd/adr/) (ADR 0001–0004) |
| Domain vocabulary | [`CONTEXT.md`](../CONTEXT.md) |
| Agent coding rules (repo-wide) | [`AGENTS.md`](../AGENTS.md) |
| Agent coding rules (backend-specific) | [`backend/AGENTS.md`](../backend/AGENTS.md) |

---

## How to use OpenWiki retrieval tools

OpenWiki is optional just-in-time context, not required startup reading. Use it when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty.

- **`openwiki_search`** — keyword search across all wiki pages; use it to locate the right page for an unfamiliar concept or component.
- **`openwiki_read`** — read one wiki page in full; use it after `openwiki_search` to get complete context on a specific area.
- **`openwiki_list_workspaces` / `openwiki_list_wikis`** — discover available workspaces when `openwiki_search` returns `workspace_required`; retry the search with the correct workspace ID.
- **Fallback (tools unavailable):** read this file (`openwiki/quickstart.md`) and follow its links to the relevant wiki sections below.

Stop retrieving once the question is grounded. Treat source code and tests as authoritative over wiki content.

---

## Release scope

**Release 1 (build now):** modules `knowledge`, `subjects`, `tutoring`, `learning`, `accounts`, `insights`.

**Stub modules — do not build until asked:**

| Module | Reserved for |
|---|---|
| `graph` | R2 — research map (citation links, timeline, reading order) |
| `catalog` | R3 — topic catalog from document headings |
| `quizzes` | R3 — multiple-choice quizzes from Lesson Notes |
| `recommendations` | R3 — "what to learn next" |
| `reports` | R3 — daily/weekly summaries |

All five stub modules have the standard `domain/application/ports/adapters/` scaffold but contain no working logic.

---

## Repository map

| Path | What |
|---|---|
| `backend/` | Python package `smart_tutor` (API, agent, RAG MCP server, ingestion worker, CronJobs), `tests/`, `evals/` |
| `web/` | React + TypeScript + Vite; one folder per feature in `src/features/`; API calls only through `src/api/` |
| `infra/` | AWS CDK app (Python, separate `uv` project), one stack per concern |
| `deploy/helm/` | Umbrella Helm chart `smart-tutor` and cluster add-on values |
| `local/` | Compose-only files: Keycloak realm, LocalStack init, Postgres init |
| `sdd/` | PRD, design specs, ADRs, reviews |

### Backend module layout

```
smart_tutor/
├── shared/          # kernel: ids, TokenUsage, Citation, errors; ChatModel/EmbeddingModel/Clock ports;
│                    #   ModelFactory; bedrock, auth (JWT), postgres, aws adapters; config.py
├── knowledge/       # library: contents (SHA-256 dedupe, states, retry), documents, can_read, upload, ingestion, search
├── subjects/        # shared subject catalog, personal names, suggestion ranking, name checks
├── tutoring/        # threads (1–3 subjects, growth), detection, relevance gate, ask path
├── learning/        # Lesson Notes, learning records
├── accounts/        # learner profile and terms, rate limits and daily caps, token usage
├── insights/        # decline log
├── graph/           # [stub] R2 research map
├── catalog/         # [stub] R3 topic catalog
├── quizzes/         # [stub] R3 quizzes
├── recommendations/ # [stub] R3 recommendations
├── reports/         # [stub] R3 reports
└── apps/            # api, agent, mcp_server, worker, jobs — one composition root per deployable
```

**Module dependency order (top imports only from below):**
`reports` → `recommendations` → `quizzes | catalog` → `learning` → `tutoring` → `graph` → `knowledge` → `subjects` → `accounts | insights`

`shared` is open to all modules and imports none of them. `apps` is a leaf; nothing imports it.

---

## Product invariants

These invariants have tests or evals guarding them. Every change must keep them true.

- **Access (`can_read`):** every read of a document goes through one rule, `can_read(user, document)` (R1–R3: owner only), enforced in code and SQL by the API and MCP server. Access never depends on the prompt.
- **Deduplication:** link a file to existing content only after the **server** hashes the uploaded bytes. A browser-sent hash only finds files already in the learner's own library.
- **Subjects as ids:** store `subject_id`s everywhere; resolve names at read time (personal name, else canonical name). Documents have 1–3 subjects; threads hold 1–3 and only ever add.
- **Untrusted input:** the user's prompt and uploaded document text are both untrusted. Pass chunks to the model as quoted data and follow only the system prompt's instructions.
- **Lifecycle:** documents and Lesson Notes are archived, never deleted. Traces expire after 180 days; the decline log after 90 days; threads are kept.
- **Privacy:** the decline log stores no user id. Tokens travel in HTTP headers and runtime context only — never in prompts, logs, or traces.
- **No admin product functions** (no subject rename/merge/hide, no account deletion) until the PRD adds them.

---

## Task-routing table

| Task | Read first |
|---|---|
| Add a business rule | [Module Layer Rules](architecture/module-layer-rules.md); the owning module's `README.md` |
| Add a use case service | [Module Layer Rules](architecture/module-layer-rules.md); [Data Model](concepts/data-model.md) |
| Add an API route | [System Architecture Overview](architecture/overview.md); [Module Layer Rules](architecture/module-layer-rules.md) |
| Change the agent graph (ask flow, detection, growth) | [Ask Flow — Agent Graph](workflows/ask-flow.md); [System Architecture Overview](architecture/overview.md) |
| Change ingestion (upload, deduplication, chunking, embedding) | [Ingestion Flow](workflows/ingestion-flow.md); [Content and Document Lifecycles](concepts/content-document-lifecycle.md) |
| Add an evaluator | [LangSmith Evaluations and Release Gates](testing/evals.md) |
| Change infra or deployment | [Deployment — CDK Stacks and Helm Chart](operations/deployment.md); [System Architecture Overview](architecture/overview.md) |
| Change the web app | [System Architecture Overview](architecture/overview.md) |
| Work with the subject catalog | [Subject Catalog and Personal Names](concepts/subject-catalog.md) |
| Work with Lesson Notes or learning records | [Lesson Notes and Learning Records](workflows/lesson-notes-and-learning-records.md) |
| Understand access control or data isolation | [Access Control and Identity Propagation](concepts/access-control.md) |
| Run or write tests | [Fakes and Unit Tests](testing/fakes-and-unit-tests.md); [Isolation and Deduplication Tests](testing/isolation-tests.md) |
| Set up local development | [Local Development](operations/local-dev.md) |
| Understand the data model or schema | [Data Model](concepts/data-model.md) |
| Work with Bedrock models or switch models | [Bedrock Model Integration](integrations/bedrock-models.md) |
| Work with Keycloak auth or JWT | [Keycloak Authentication and Identity](integrations/keycloak-auth.md) |
| Work with the MCP retrieval server | [RAG MCP Server and Retrieval](integrations/mcp-retrieval.md) |
| Work with S3 storage or SQS queue | [S3 Storage and SQS Ingestion Queue](integrations/storage-s3-sqs.md) |
| Understand later-release stubs | [Later-Release Module Placeholders](modules/later-releases.md) |

---

## Wiki sections

### Architecture

| Page | What it covers |
|---|---|
| [System Architecture Overview](architecture/overview.md) | All deployables (API, agent, MCP server, ingestion worker, CronJobs, web), their responsibilities, network topology, and end-to-end request flow |
| [Module Structure and Import Rules](architecture/module-layer-rules.md) | Modular-monolith layout (`modules → domain/application/ports/adapters`), enforced import-linter contracts, acyclic module dependency order, and where new code belongs |
| [Shared Kernel](architecture/shared-kernel.md) | The `shared/` package: typed identifiers, `TokenUsage`, `Citation`, errors, `ChatModel`/`EmbeddingModel` ports, `Clock`, `ModelFactory`, and the auth/postgres/AWS/Bedrock adapters |

### Concepts

| Page | What it covers |
|---|---|
| [Data Model](concepts/data-model.md) | Every PostgreSQL table, the LangGraph store namespace, SSM parameters, and key derived values |
| [Content and Document Lifecycles](concepts/content-document-lifecycle.md) | Content state machine (`processing/ready/failed/retry`), Document state machine (`processing/awaiting_subjects/ready/failed` + archived flag), SHA-256 deduplication flow, and Glacier archiving |
| [Subject Catalog and Personal Names](concepts/subject-catalog.md) | Shared subject catalog design, personal names, suggestion ranking, name normalization and checks, and subject id stability invariants |
| [Access Control and Identity Propagation](concepts/access-control.md) | `can_read` rule, JWT forwarding chain from web to MCP server, SQL search filter construction, and learner isolation guarantee |

### Integrations

| Page | What it covers |
|---|---|
| [AWS Bedrock Model Integration](integrations/bedrock-models.md) | Model roles, model IDs, Bedrock adapter design (`ChatModel`/`EmbeddingModel`), `ModelFactory`, and rules for switching models |
| [Keycloak Authentication and Identity](integrations/keycloak-auth.md) | Keycloak configuration, OIDC flow, realm structure, test users, JWT validation in the API and MCP server, and the role model |
| [RAG MCP Server and Retrieval](integrations/mcp-retrieval.md) | MCP server tools (`search`, `get_chunk`), access-enforced SQL filter, iterative HNSW search, and the `Retriever` port used by the agent |
| [S3 Storage and SQS Ingestion Queue](integrations/storage-s3-sqs.md) | S3 bucket layout, presigned POST upload flow, S3 event notifications to SQS, Glacier lifecycle, and LocalStack emulation |

### Workflows

| Page | What it covers |
|---|---|
| [Ask Flow — Agent Graph](workflows/ask-flow.md) | Complete ask-path through the LangGraph agent: subject detection, MCP search, relevance gate, growth check, answer generation, and the decline path |
| [Ingestion Flow](workflows/ingestion-flow.md) | Full document processing pipeline: upload, SHA-256 deduplication, first-pages step, Docling extraction, chunking, embedding, and subject suggestion |
| [Lesson Notes and Learning Records](workflows/lesson-notes-and-learning-records.md) | Learning module: one-per-thread Lesson Notes (create/overwrite with confirmation/archive), learning records (note trigger and idle trigger), and the record sweeper CronJob |

### Modules

| Page | What it covers |
|---|---|
| [Later-Release Module Placeholders](modules/later-releases.md) | The five empty stub modules (`graph`, `catalog`, `quizzes`, `recommendations`, `reports`), what each will own, and how they fit into the module dependency order |

### Testing

| Page | What it covers |
|---|---|
| [Fakes and Unit Tests](testing/fakes-and-unit-tests.md) | `FakeChatModel`, `FakeEmbeddingModel`, how to write unit tests with them, and test layout conventions |
| [Isolation and Deduplication Tests](testing/isolation-tests.md) | The `tests/isolation/` suite: what it asserts about cross-user access and deduplication, and why these tests exist |
| [LangSmith Evaluations and Release Gates](testing/evals.md) | LangSmith datasets, evaluator modules, adversarial taxonomy, seed corpus, `thresholds.yaml` release gates, and how to run eval splits |

### Operations

| Page | What it covers |
|---|---|
| [Local Development](operations/local-dev.md) | How to start the local stack (Docker Compose), run lint, unit tests, integration tests, evals, the web app, and all Makefile targets |
| [Deployment — CDK Stacks and Helm Chart](operations/deployment.md) | AWS CDK stack structure, Helm umbrella chart, delivery pipeline, and production environment configuration |

---

## Quick start: run locally

```bash
cp .env.example .env          # fill in AWS_PROFILE and LANGSMITH_API_KEY
make up                       # starts pgvector, Keycloak (:8080), LocalStack (:4566)
make sync                     # installs backend dependencies
make lint test                # ruff, mypy, import-linter contracts, unit tests
make web                      # http://localhost:5173
```

Test users: `learner@example.com` / `learner`, `learner2@example.com` / `learner2`, `admin@example.com` / `admin`. Keycloak admin console: http://localhost:8080 (admin / admin).

> **Note:** Bedrock and LangSmith have no local emulator. Local runs call real `us-east-1` Bedrock models using the configured AWS profile.

For full details see [Local Development](operations/local-dev.md).
