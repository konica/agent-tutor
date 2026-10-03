# 0001. Modular monolith with enforced import contracts

- Status: accepted
- Date: 2026-10-02

## Context

All backend deployables (API, agent, MCP server, ingestion worker, CronJobs) share one domain. The roadmap adds a module per release (research map, learning loop, sharing, deep graph). We want features added as new folders, clear ownership, and layering that holds up without relying on review alone.

## Decision

- One Python package `smart_tutor` with extras for heavy, single-service dependencies (`ingest` = Docling, worker image only; `eval`).
- **Modules first**, with `domain / application / ports / adapters` inside each module; a small `shared` kernel; entrypoints in `apps/` (one composition root per deployable).
- Modules use each other only through `application`; the module order is explicit and acyclic.
- **import-linter** contracts in `backend/pyproject.toml` enforce layers, module privacy, apps as leaves, vendor SDKs only in adapters, Docling only in `knowledge.adapters`, and the module order. CI fails on any broken contract.

## Consequences

- A new cross-module dependency means editing the module order on purpose.
- Flows that go against the order are orchestrated in `apps/`.
- More folders than a layer-first layout at pilot size; in exchange, later releases don't touch Release 1 modules.

Details: `sdd/specs/2026-10-02-project-structure-design.md`.
