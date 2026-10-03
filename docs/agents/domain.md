# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

Layout: **single-context**. Decided in `sdd/reviews/2026-10-03-delivery-process-discussion.md`.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: the glossary, seeded from `sdd/prd.md` §4.
- **`sdd/adr/`**: read ADRs that touch the area you're about to work in. This repo keeps ADRs here, not in `docs/adr/`; number new ones after the highest existing file and follow `sdd/adr/README.md`.
- **`sdd/prd.md`**: the product source of truth. Story IDs (`US-1` … `US-20`) are stable; cite them with the section (e.g. "PRD §8 US-4").

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill (reached via `/grill-with-docs` and `/improve-codebase-architecture`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md
├── sdd/
│   ├── prd.md
│   ├── specs/
│   └── adr/
│       ├── 0001-modular-monolith.md
│       └── …
└── backend/src/smart_tutor/<module>/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

If `CONTEXT.md` and `sdd/prd.md` §4 disagree, the PRD wins; update `CONTEXT.md` in the same PR.

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0003 (shared subject catalog), but worth reopening because…_
