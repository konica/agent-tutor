# `tutoring` module (Release 1)

**Owns** (PRD §9.2, US-3, US-4 to US-6, US-13): Threads (no subjects; they keep their documents used (US-4b)), relevance gate, the ask path, conversation management.

**Key classes:** `Thread`, `RelevanceGate`; services `AskService`, `ConversationService`; ports `Retriever`, `ThreadRepository`.

**Built so far:** `Thread` and `ThreadRepository` (`SqlThreadRepository`); `ConversationService.require_documents` / `start_thread(user_id, question)` (a learner with no ready, non-archived document gets "Upload a document first"; the title starts as the first question); `rename_thread` (`Thread.rename`: trimmed, 1–120 characters, refused while archived); `Retriever` with its MCP client adapter `McpRetriever` (`search(query, k)` over all of the learner's ready documents); `answer_messages` / `cited_chunks` (the quoted answer prompt and its citations); documents used: `ConversationService.record_answer` (adds an answer's documents in order of first use, no duplicates) and `documents_used` (resolved now: title, authors, year, archived, or "Deleted document"), stored as `ThreadDocument` rows; `ConversationService.keep_deleted_title(user_id, document_id, title)` copies a document's title onto its rows in that learner's threads just before the document is deleted. `AskService`, `RelevanceGate`, and conversation management are still to come.

**May use (application layer only):** `knowledge` (whether the learner has a ready document), `subjects`, `accounts`, `insights` (log declines). Everyone may use `shared`.

**Rules:** Never reads chunk tables: retrieval goes through the `Retriever` port (MCP client adapter). A thread has no subjects and answers from all of the learner's ready documents. Document text is passed to the model as quoted data. Never imports `learning`.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `tutoring.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
