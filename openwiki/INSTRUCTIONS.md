# OpenWiki brief: Smart Tutor

Audience: coding agents working in this repository. Humans read the same pages.

## Sources of truth

The wiki is a **generated view**. It never overrides these authored files; when they disagree with code, say so on the page instead of choosing:

- `sdd/prd.md`: product behavior, user stories (`US-*`), data model, flows, roadmap. Cite sections, e.g. "PRD §9.2".
- `sdd/specs/2026-10-02-project-structure-design.md`: module boundaries and import rules.
- `sdd/adr/`: architecture decisions. Link the ADR instead of restating it.
- `CONTEXT.md`: glossary. Use its terms; avoid the synonyms it lists under _Avoid_.
- `AGENTS.md`, `backend/AGENTS.md`: agent working rules.

## Cover, in this order

1. Architecture: deployables (API, agent, MCP server, ingestion worker, CronJobs, web) and how a request flows between them.
2. Backend modules (`knowledge`, `subjects`, `tutoring`, `learning`, `accounts`, `insights`) and their `domain` / `application` / `ports` / `adapters` layers: what exists today, what is a stub.
3. Ports and adapters: model abstraction (`ChatModel`, `EmbeddingModel`, `ModelFactory`), storage, MCP.
4. Access and identity: `can_read`, JWT forwarding, isolation tests.
5. Local development, checks, CI, and deployment (Compose, Makefile, CDK stacks, Helm chart).
6. Tests and evals: fakes, isolation suite, LangSmith evals and thresholds.

Release 2–5 modules (`graph`, `catalog`, `quizzes`, `recommendations`, `reports`) get one short page saying they are placeholders.

## Style

- Plain, short sentences. State what the code does now; mark planned behavior as "planned (PRD §x)".
- Never include secrets, tokens, account ids, or values from `.env`.
