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
