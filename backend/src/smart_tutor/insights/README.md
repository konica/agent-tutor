# `insights` module (Release 1)

**Owns** (§9.6, US-11): Content-gap capture and the weekly content-gap report.

**Key classes:** `ContentGap`; service `ContentGapService`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Never stores a user id with a content gap.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `insights.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
