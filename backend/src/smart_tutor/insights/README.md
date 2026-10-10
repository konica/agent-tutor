# `insights` module (Release 1)

**Owns** (§9.6): Anonymized decline log and quality monitoring queries; the count of citation highlights the viewer couldn't draw.

**Key classes:** `Decline`; services `DeclineLogService`, `HighlightMissService`; port `HighlightMissCounter`.

**May use (application layer only):** none. Everyone may use `shared`.

**Rules:** Never stores a user id with a decline. The highlight-miss count is one number per UTC day: never a user id, chunk, document, or text.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `insights.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
