# 0015. Conversation history lives in a tutoring-owned table

- Status: accepted
- Date: 2026-10-10

## Context

US-13 reopens a conversation with its history. The ask graph answers one turn at a time and has no checkpointer (#31). Multi-turn chat (US-4) will later read a capped history of earlier turns.

## Decision

- **History is a PostgreSQL table, `thread_turns`, owned by `tutoring`.** The API writes a row when an answer ends with `done`, and reads rows through owner-scoped SQL.
- **The LangGraph checkpointer is not used for history.**
- **Citations are stored as ids and a page** (`document_id`, `chunk_id`, `page`). Titles resolve at read time.

## Why

- **One place for the rules.** The API already sees every event and owns the thread. It can enforce "only saved turns count" (US-4b) and owner scoping in SQL in one spot.
- **Checkpoints are the wrong store.**
  - They hold graph state, including retrieved chunk text, which PRD §9.2 says must not be kept.
  - They are keyed by thread and have no owner column.
  - SQL can't list, filter, or expire them in a useful way.
- **Deletes need no rewrite.** A citation is ids, so a deleted document reads "Deleted document" without editing any turn.

## Consequences

- Multi-turn chat (US-4) passes the last N turns from this table to the agent in the ask request, capped, still without a checkpointer.
- One new table to migrate (`0014`).
- Turns are deleted only with their thread, and threads are kept.
