# AGENTS.md

Instructions for coding agents in this repository. Before changing Python code, also read `backend/AGENTS.md` (it takes precedence inside `backend/`).

## Project

Smart Tutor is an AI tutor for the learner's **own PDFs**. Learners upload documents into a private library; each document gets 1–3 subjects from a **shared subject catalog**. A conversation has no subjects: it answers only from all of the learner's ready documents, with citations, and lists the documents it used; a citation opens the PDF at the highlighted passage. Each learner's upload is processed and embedded for that learner; nothing is linked across learners.

Sources of truth — read the relevant one before changing behavior or structure:

| Need | Read |
|---|---|
| Product behavior, user stories, data model, flows, evals, roadmap | `sdd/prd.md` (v2.48) |
| Folder structure, module boundaries, import rules | `sdd/specs/2026-10-02-project-structure-design.md` |
| Why an architecture choice was made | `sdd/adr/` (0001–0016) |
| Why the PRD changed in v2.1 | `sdd/reviews/2026-10-03-prd-v2.0-review.md` |

**Release scope:** build **Release 1** (core tutor: modules `knowledge`, `subjects`, `tutoring`, `learning`, `accounts`, `insights`). Later releases already have empty modules and prepared data (R2 research map → `graph`; R3 `catalog`, `quizzes`, `recommendations`, `reports`; R4 sharing and imports; R5 deep graph); build them only when asked.

## Repository map

| Path | What |
|---|---|
| `backend/` | The one Python package `smart_tutor` (API, agent, RAG MCP server, ingestion worker, CronJobs), `tests/`, `evals/` |
| `web/` | React + TypeScript + Vite; one folder per feature in `src/features/`; API calls only through `src/api/` (generated from the API's OpenAPI schema) |
| `infra/` | AWS CDK app (Python, separate uv project), one stack per concern |
| `deploy/helm/` | Umbrella chart `smart-tutor` and cluster add-on values |
| `local/` | Compose-only files: Keycloak realm, LocalStack init, Postgres init |
| `sdd/` | PRD, specs, plans, ADRs, reviews; `sdd/design/` holds the design brief, the Open Design prototype, and accepted rounds |

## Product invariants

Code must keep these true; each has tests or evals guarding it.

- **Access:** every read of a document goes through one rule, `can_read(user, document)` (Release 1: owner only), enforced in code and SQL by the API and MCP server. Access never depends on the prompt.
- **Per-learner contents:** a content belongs to one learner, unique per `(owner_id, sha256)`. Never link an upload to another learner's content; duplicates are caught only within the learner's own library (browser hash before upload, server hash after it). ADR 0011.
- **Subjects:** store `subject_id`s everywhere; resolve names at read time (personal name, else canonical name). Documents have 1–3 subjects; threads have none (they keep their documents used).
- **Untrusted input:** the user's prompt and uploaded document text. Pass chunks to the model as quoted data and follow only the system prompt's instructions.
- **Lifecycle:** documents are archived or deleted by their owner (delete only when not processing or shared; it removes the PDF, page text, and chunks, and references show "Deleted document"); Lesson Notes are archived, never deleted. Traces expire after 180 days, the decline log after 90; threads are kept.
- **Privacy:** the decline log stores no user id. Tokens travel in HTTP headers and runtime context only — never in prompts, logs, or traces.
- **No admin product functions** (no subject rename/merge/hide, no account deletion) until the PRD adds them.

## Local development

- `docker compose up -d` starts pgvector (host port 10400), Keycloak (:10401), LocalStack (:10402), and Mailpit (:10403, web UI for emails Keycloak sends); `--profile app` adds api (:10450), agent (:10451), mcp (:10452), and web (:10453). Host ports count up from 10400 for dependency services and from 10450 for app services; a new service takes the next free port in its group. Copy `.env.example` to `.env`.
- To iterate faster, run the app services on the host on the same ports: `make api`, `make agent`, `make mcp`, `make worker`, and `make web` (README "Run the app"). Start host backend processes with `uv run --env-file ../.env`; otherwise boto3 skips LocalStack and calls real AWS. To debug, use `make <service>-debug` (debugpy listens at app port + 10, 10460–10463) or the checked-in `.vscode/launch.json` (README "Debug the backend").
- The worker, agent, and MCP server call Bedrock with your AWS profile (in Compose, `~/.aws` is mounted read-only); the worker's S3/SQS calls use LocalStack's dummy keys (`SMART_TUTOR_LOCALSTACK`).
- Bedrock and LangSmith have no emulator: local runs call real us-east-1 models with your AWS credentials. `make bedrock-check` (pytest marker `bedrock`, under a cent) verifies the configured models and adapters.
- Keycloak users: `learner@example.com`/`learner`, `learner2@example.com`/`learner2`, `admin@example.com`/`admin` (console admin/admin). The realm imports only when it doesn't exist yet: run `docker compose down -v` after editing `local/keycloak/realm-smart-tutor.json`, and keep the built-in roles `offline_access` and `uma_authorization` defined in it.
- `make migrate` applies Alembic migrations to the Compose database (the app profile runs it before the API). After changing an API route, run `make api-client` to regenerate `web/src/api/`; CI fails when it is stale.
- Windows Git Bash: set `PYTHONUTF8=1` for `lint-imports` and `MSYS_NO_PATHCONV=1` for commands taking `/smart-tutor/...` paths (SSM names). `make` may be missing; every `Makefile` target is a one-line command you can run directly.

## Checks

Run before committing; CI (`.github/workflows/ci.yml`) runs the same.

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
cd web && npm ci && npm run build                 # when web/ changed
cd infra && uv run pytest                         # when infra/ changed
helm lint deploy/helm/smart-tutor                 # when deploy/ changed
```

Other tasks (Compose, jobs, evals, CDK synth) are targets in the `Makefile`; image build commands are in the header of `backend/Dockerfile`.

## Tests and evals

- Every behavior change comes with tests. Unit tests use the fakes in `backend/tests/fakes/`; real Bedrock is reached only by evals.
- Endpoints and MCP tools that return learner data get a test in `backend/tests/isolation/`.
- Agent quality is gated by LangSmith evals in `backend/evals/`, targets in `thresholds.yaml`, data from the seed corpus manifest. Fix the agent until a run meets its threshold.

## Agent skills

### Issue tracker

GitHub Issues in `konica/agent-tutor`: milestones M0–M4, one parent issue per user story, slices as sub-issues, `area:*` labels. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`, with `bug`/`enhancement`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` at the root, ADRs in `sdd/adr/`. See `docs/agents/domain.md`.

### Workflow: which skill does what

mattpocock skills decide **what** to build and run the tracker; superpowers skills build **one ticket**. Use one skill per stage.

| Stage | Skill | Output |
|---|---|---|
| Open decisions | `wayfinder` (with `grilling`, `domain-modeling`) | Decision tickets on the map; ADRs; `CONTEXT.md` terms |
| Slice a story | `to-tickets` | Sub-issues of the story parent, with blocking edges |
| Intake | `triage` | Category and state labels; agent brief |
| Design one slice (only when it needs design) | superpowers `brainstorming` | Design doc in `sdd/specs/YYYY-MM-DD-<topic>-design.md` |
| Plan one slice | superpowers `writing-plans` | Plan in `sdd/plans/YYYY-MM-DD-<feature>.md` |
| Build | superpowers `subagent-driven-development` (or `executing-plans`), `test-driven-development` | Commits, each task reviewed |
| Finish | superpowers `requesting-code-review`, `finishing-a-development-branch` | PR that closes the issue |

- Build with superpowers, not mattpocock `implement`/`tdd`.
- `grilling` is for project-level decision tickets; `brainstorming` is for designing one slice.
- Save superpowers specs and plans under `sdd/`, not `docs/superpowers/`. The PRD stays the product spec; a design doc narrows it for one slice and cites its PRD section.
- Decided in `sdd/reviews/2026-10-03-delivery-process-discussion.md`.

## Design inputs

Mockups live in `sdd/design/` (brief, prototype, accepted rounds). Process: `sdd/specs/2026-10-03-design-to-code-loop-design.md`; commands: `sdd/design/README.md`. **Visual rules** (tokens, themes, app shell, components, document states, accessibility): `DESIGN.md`, read before writing UI in `web/src/`.

1. Read the ticket's `## Design` section, then the round's row in `sdd/design/rounds.md`.
2. Render the ticket's states and look at them before writing code: `make design-shots ROUND=v0.4 STATES="chat-*" THEME=both` (PNGs in `.design-shots/`). First time: `cd web && npx playwright install chromium`.
3. The prototype is a spec, not code to copy. Rebuild it with `web/src/components/` and the design tokens; never paste prototype HTML or CSS into a feature.
4. If the mockup and the PRD disagree, follow the PRD and record the conflict in the PR description and the brief's Feedback log.
5. Read the prototype at the ticket's tag (`ROUND=`), not the working copy, which may hold a round in progress. Never read Open Design or its data folder.
6. After changing `sdd/design/prototype/`, run `make design-states`; CI fails when `sdd/design/states.json` is stale.

## Commits, PRs, and docs

- Work on a branch and open a PR into `main`. Commit subjects in the imperative mood; the body says why.
- **Stacked PRs:** when a PR's base is another PR's branch, merge the base first **and delete its branch**, so GitHub retargets the stacked PR to `main`. Otherwise the stacked PR merges into the stale branch and never reaches `main`.
- A change to product behavior updates `sdd/prd.md` in the same PR and bumps its version in the status line. A new architecture decision gets an ADR in `sdd/adr/`; a structure change updates the spec.

<!-- OPENWIKI:START -->

## OpenWiki

This repository has a generated `openwiki/` evidence index. It is optional just-in-time context, not required startup reading.

- Do not enumerate, preload, or search wikis at task start. Use retrieval when the user asks for it, when unfamiliar architecture or dependency behavior materially affects the task, or when source inspection leaves an important uncertainty. Stop once the question is grounded.
- When those conditions apply and OpenWiki retrieval tools are available, use `openwiki_search` for just-in-time context and `openwiki_read` for the relevant complete sections. If search returns `workspace_required`, ask which listed workspace to use and retry with its ID.
- Use `openwiki_list_workspaces` or `openwiki_list_wikis` when workspace membership itself needs to be discovered.
- If the retrieval tools are unavailable, read `openwiki/quickstart.md` and follow its links to the relevant pages.
- Treat source code and tests as authoritative. A brief's unknowns and review items are verification gaps, not automatic requirements.
- Prefer the narrowest quiet validation that proves the changed behavior. Preserve complete failure output.

The scheduled OpenWiki GitHub Actions workflow refreshes the repository wiki. Do not hand-edit generated OpenWiki pages unless explicitly asked; prefer updating source code/docs and letting OpenWiki regenerate.

<!-- OPENWIKI:END -->
