# `insights` module (Release 1)

**Owns** (§9.6): Anonymized decline log and quality monitoring queries.

**Key classes:** `Decline`; service `DeclineLogService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Never stores a user id with a decline.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `insights.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
