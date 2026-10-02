# Smart Tutor — Project Structure Design

| | |
|---|---|
| **Status** | Approved 2026-10-02; scaffolded |
| **Date** | 2026-10-02 |
| **Based on** | `sdd/prd.md` v1.5 (§9.11–§9.15, §10, §14) |
| **Scope** | Folder structure for the whole repository, Python packaging, module boundaries, and the import rules CI enforces |

## 1. Goals

- A new developer can find where any PRD component lives and where new code belongs.
- Release 2 (quizzes, reports, recommendations, topic catalog) and later releases are added as **new folders**, without changing Release 1 modules (PRD §9.15).
- The layering in PRD §9.15 is **enforced automatically** in CI, not just documented.
- Each container image installs only the dependencies its service needs.

## 2. Decisions

| # | Decision | Rationale |
|---|---|---|
| S1 | **One Python package** (`smart_tutor`) with one `pyproject.toml`; heavy dependencies sit behind **extras**: `[ingest]` (Docling), `[eval]` (evaluation deps); development tools are a uv `dev` dependency group (never installed in images). Each Docker build target installs only the extras it needs. | Matches the PRD's "one package shared by all deployables" while keeping Docling/PyTorch out of the API, agent, and MCP images. A uv workspace with several packages was rejected as too heavy for the team size. |
| S2 | **Modules first, layers inside each module** (modular monolith). Each module has `domain/`, `application/`, `ports/`, `adapters/`. | Long-term: a feature is one folder; R2/R3 add folders, not files spread across five layer folders; modules can be owned independently and split out later if ever needed. |
| S3 | **Entrypoints live in `smart_tutor/apps/`**, one composition root per deployable, not inside modules. | A deployable spans modules (the API serves all of them; the agent graph uses `tutoring` and `learning`). Wiring stays in one place per deployable. |
| S4 | Modules talk to each other **only through the other module's `application` layer** (and the `shared` kernel). | Prevents coupling through domain internals or tables; e.g. `reports` reads learning records via a `learning` service, never its tables. |
| S5 | A small **`shared` kernel** holds cross-module value objects, the model ports, `ModelFactory`, auth, and infrastructure clients. | One home for the model abstraction (PRD D15) and identity (PRD §9.3). Kept small on purpose. |
| S6 | `backend/` and `infra/` are **separate Python projects**. | The CDK app (`aws-cdk-lib`) has unrelated dependencies that must not enter application images. |
| S7 | **Local development uses Docker Compose only**; Helm has `values.yaml` and `values-prod.yaml`. | PRD §9.12: Compose locally, EKS + Helm in production. |
| S8 | The two PDFs under `data/` are **not tracked**; `data/` is ignored. | They are not the product corpus (Admins upload documents to S3). |

**PRD follow-up:** §9.15 describes the five layers at the top of the package. With S2/S3 the same layers sit inside each module and entrypoints move to `apps/`. Update PRD §9.15 wording in v1.6.

## 3. Repository top level

```
agent-tutor/
├── README.md
├── Makefile                 # one entry point: make up, make test, make lint, make sweep, make reports
├── compose.yaml             # local dependencies (default) + `app` profile (same images as prod)
├── .env.example
├── .gitignore  .editorconfig  .pre-commit-config.yaml
├── .github/workflows/       # ci.yml (lint, import contracts, tests, smoke evals); deploy.yml (ECR → cdk deploy → helm upgrade)
│
├── sdd/                     # product and design docs
│   ├── prd.md
│   ├── specs/               # design specs (this document)
│   ├── adr/                 # architecture decision records
│   └── design-briefs/       # versioned briefs for the designer
│
├── backend/                 # the one Python package (S1)
│   ├── pyproject.toml       # extras: [ingest], [eval]; dev group; import-linter contracts
│   ├── uv.lock
│   ├── Dockerfile           # multi-stage; targets: api, agent, mcp, worker (CronJobs reuse the api image)
│   ├── src/smart_tutor/     # §4
│   ├── tests/               # §6
│   └── evals/               # §7
│
├── web/                     # React + TypeScript (Vite); own package.json and Dockerfile (nginx)   §9
├── infra/                   # AWS CDK app (Python); own pyproject.toml                            §8
├── deploy/helm/             # umbrella chart and cluster add-on values                             §8
│
└── local/                   # files only Compose uses
    ├── keycloak/realm-smart-tutor.json   # clients, roles, audience mapper, test users
    ├── localstack/init/                  # bucket, SQS + DLQ, S3 → SQS notifications, SSM parameters
    └── postgres/init/                    # app and Keycloak databases, pgvector extension
```

## 4. Inside `smart_tutor`

```
backend/src/smart_tutor/
├── shared/
│   ├── domain/        # ids.py (UserId, ThreadId, SubjectId), token_usage.py, citation.py, errors.py
│   ├── ports/         # chat_model.py (ChatModel), embedding_model.py (EmbeddingModel), clock.py
│   ├── adapters/
│   │   ├── bedrock/           # BedrockConverseChatModel, NovaEmbeddingModel
│   │   ├── model_factory.py   # builds models by role: agent | judge | embedding
│   │   ├── auth/              # Keycloak JWT verifier (API and MCP server)
│   │   ├── postgres/          # engine, session, unit of work
│   │   └── aws/               # S3, SQS, SSM clients
│   └── config.py      # pydantic-settings; model roles; SSM-backed settings
│
├── knowledge/         # documents, chunks, ingestion, search
├── tutoring/          # threads, subject detection, ask
├── learning/          # Lesson Notes, learning records
├── accounts/          # learners, enrollments, token usage, rate-limit policy
├── insights/          # content gaps and the weekly report
├── catalog/           # (R2) topic catalog from Docling headings
├── quizzes/           # (R2)
├── recommendations/   # (R2)
├── reports/           # (R2)
│
└── apps/              # entrypoints: parse input, call application services, format output; no business rules
    ├── api/           # main.py, deps.py (wiring), routes/ (one file per module), sse.py, rate_limit.py
    ├── agent/         # server.py, graph.py, state.py, nodes/ (resolve_subject, search, gate, answer, summarize)
    ├── mcp_server/    # server.py, tools.py (search, get_chunk) → knowledge.application
    ├── worker/        # SQS consumer → knowledge.application.IngestionService
    └── jobs/          # record_sweeper.py, content_gap_report.py, (R2) learner_reports.py
```

Every module has the same shape:

```
<module>/
├── README.md        # responsibility, public services, what it must not do
├── domain/          # entities and value objects with their rules; no I/O
├── application/     # services, one per use case; the module's public API
├── ports/           # abstract interfaces (ABCs) the module needs
└── adapters/        # implementations of ports; the only place vendor SDKs appear
```

## 5. Module boundaries

| Module | Owns (PRD) | Key classes | Depends on (application of) |
|---|---|---|---|
| `knowledge` | Documents, versions, archive, chunks, ingestion, search (§9.5, US-10) | `Document`, `Chunk`; `IngestionService`, `SearchService`; ports `PdfExtractor`, `DocumentStore`, `ChunkRepository` | `accounts` (enrolled subjects for the search filter) |
| `tutoring` | Threads, subject binding and detection, relevance gate, ask path (§9.2, US-3–US-6, US-13) | `Thread`, `DetectionPolicy`, `RelevanceGate`; `SubjectDetector`, `AskService`, `ConversationService`; ports `Retriever`, `ThreadRepository` | `accounts`, `insights` (log declines) |
| `learning` | Lesson Notes, learning records, idle sweep (§9.4, US-7, US-8, US-13b) | `LessonNote`, `LearningRecord`; `NoteService`, `LearningRecordService`; ports `NoteRepository`, `LearningMemory` | `tutoring` (thread content) |
| `accounts` | Learners, enrollments, time zone, token usage, rate-limit policy (US-2, US-9) | `Learner`, `Enrollment`; `EnrollmentService`, `UsageService` | — |
| `insights` | Content-gap capture and weekly report (§9.6, US-11) | `ContentGap`; `ContentGapService` | — |
| `catalog` (R2) | Topic catalog (§9.7) | `TopicEntry`; `CatalogService` | `knowledge` |
| `quizzes` (R2) | Quiz generation and grading (US-14) | `Quiz` (`grade(answers)`); `QuizService` | `learning` |
| `recommendations` (R2) | "What to learn next" (US-16) | `Recommendation`; `RecommendationService` | `catalog`, `quizzes`, `learning` |
| `reports` (R2) | Daily/weekly reports (§9.8, US-15) | `Report`; `ReportService` | `learning`, `quizzes`, `recommendations` |

The agent never reads chunk tables: `tutoring`'s `Retriever` port is implemented by an MCP client adapter that calls `apps/mcp_server`, which calls `knowledge.application.SearchService`. This keeps the access boundary of PRD §9.3 in the code structure.

The dependency graph between modules must stay **acyclic**; if two modules need each other, the shared piece moves to `shared` or one side defines a port. Flows that span modules in the "wrong" direction are orchestrated in `apps`, e.g. "Discuss this note" (`apps/api` reads the note from `learning`, then starts a thread in `tutoring`), so `tutoring` never imports `learning`.

## 6. Import rules (import-linter, run in CI)

| # | Contract | Rule |
|---|---|---|
| 1 | Layers (one `layers` contract with `containers` = every module, incl. `shared`) | `adapters` \| `application` → `ports` → `domain`. `adapters` and `application` never import each other. |
| 2 | Module privacy (`forbidden`) | A module may import from another module only its `application` package; everyone may import `shared`. |
| 3 | Apps are leaves (`forbidden`) | Nothing imports `smart_tutor.apps`. |
| 4 | Vendor SDKs (`forbidden`, external packages) | `docling` only from `knowledge.adapters`; `boto3`/`botocore`, `langgraph`, `langchain_aws`, `mcp` only from `adapters` or `apps`. |
| 5 | Module graph (`layers` over modules) | Explicit order, top to bottom: `reports` → `recommendations` → `quizzes` \| `catalog` → `learning` → `tutoring` \| `knowledge` → `accounts` \| `insights`. Lower never imports higher, so there are no cycles; a new cross-module dependency means editing this order on purpose. |

## 7. Tests and evaluations

```
backend/tests/
├── unit/<module>/          # domain + application with fakes; no I/O
├── integration/<module>/   # adapters against the Compose stack; pytest marker `integration`
├── isolation/              # US-12: cross-user and cross-subject access tests against API and MCP
├── fakes/                  # FakeChatModel, FakeEmbeddingModel, in-memory repositories
└── conftest.py

backend/evals/              # datasets live in LangSmith (versioned there); the repo holds what builds and runs them
├── generators/             # synthetic Q&A, off-topic and near-scope negatives, detection/ambiguous, multi-turn switches
├── adversarial/            # taxonomy.yaml + seed prompts (PRD §10.3)
├── evaluators/             # one file per PRD §10.1 evaluator; rubrics/ for Qwen judge prompts
├── targets.py              # how an evaluation run invokes the agent
├── thresholds.yaml         # PRD §10.1 targets, read by the release gate
└── run.py                  # run --split smoke|full → LangSmith experiment
```

## 8. Infrastructure and deployment

```
infra/
├── app.py  cdk.json  pyproject.toml
├── smart_tutor_infra/stacks/   # network, data (RDS), storage (S3 + SQS/DLQ + lifecycle), cluster (EKS + Pod Identity),
│                               # registry (ECR), config (SSM, Secrets Manager), budgets
└── tests/                      # CDK assertion tests

deploy/helm/
├── smart-tutor/                # umbrella chart: Chart.yaml, values.yaml, values-prod.yaml
│   └── charts/                 # api, agent, mcp-server, worker, web, jobs (CronJobs), keycloak (wraps upstream chart)
│                               # each sub-chart owns its NetworkPolicy and ExternalSecret
└── addons/                     # values for AWS Load Balancer Controller, External Secrets Operator, metrics-server
```

## 9. Web app

```
web/src/
├── features/     # enrollment, chat, conversations, notes, usage; (R2) quizzes, reports
├── api/          # typed client generated from the API's OpenAPI schema
├── auth/         # Keycloak OIDC (Authorization Code + PKCE)
└── components/   # shared UI
```

## 10. Scaffold scope (first implementation step)

**Included:**
- All folders above, with `__init__.py` files and a `README.md` per module stating its responsibility, public services, and dependencies.
- `backend/pyproject.toml` with extras and the import-linter contracts of §6; `make lint` runs them.
- `shared/ports` stubs: `ChatModel`, `EmbeddingModel` (signatures from PRD §9.15), `Clock`.
- Root `Makefile`, `compose.yaml` (pgvector, Keycloak, LocalStack), `.env.example`.
- Minimal placeholders for `backend/Dockerfile`, `infra/` (CDK app that synthesizes empty stacks), `deploy/helm/smart-tutor/Chart.yaml`, and `web/` (Vite React TypeScript skeleton).
- `data/` untracked and ignored (S8).

**Not included:** feature logic, real CDK resources, Helm templates, CI workflows beyond lint and unit tests. These are M0 tasks in PRD §14.

## 11. Success criteria

- `make lint` passes the import contracts on the empty scaffold, and fails if a test import breaks a rule (e.g. `tutoring.application` importing `knowledge.domain`).
- `make test` runs (zero tests) and `make up` starts the Compose dependencies.
- Every PRD component in §9.1 maps to exactly one folder.
