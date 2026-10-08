# `tutoring` module (Release 1)

**Owns** (PRD §9.2, US-3, US-3b, US-4 to US-6, US-13): Threads (1–3 subjects, grow to at most 3 with notices and a warning at the maximum), subject detection, relevance gate, growth check, the ask path, conversation management.

**Key classes:** `Thread` (`add_subject()` refuses beyond 3, never removes), `DetectionPolicy`, `RelevanceGate`, `GrowthPolicy`; services `SubjectDetector`, `AskService`, `ConversationService`; ports `Retriever`, `ThreadRepository`.

**Built so far:** `Thread` and `ThreadRepository` (`SqlThreadRepository`); `DetectionPolicy`, `SubjectDetector` (one search, k = 20, over all of the learner's subjects; unsure asks the learner), `ConversationService.subjects_for_new_thread` / `start_thread(user_id, subject_ids)` (refuses subjects that aren't the learner's); `Retriever` with its MCP client adapter `McpRetriever`; `answer_messages` / `cited_chunks` (the quoted answer prompt and its citations). Detection thresholds come from SSM (`load_detection_policy`). The rest above is still to come.

**Pending threads (US-3 criterion 3, #85):** when detection is unsure, `ConversationService.start_pending_thread` creates a thread with no subjects and the first question as its `title` (`Thread.pending`). The agent graph pauses at `choose_subjects` (LangGraph interrupt, question held in the checkpointer keyed `user_id/thread_id`); On the learner's pick, the API checks it first (`pending_thread`, then `check_choice`), the agent resumes with it, and the API binds it with `ThreadRepository.bind_subjects` (only the owner's still-unbound thread) when the agent's resumed `subjects` event arrives. `pending_thread` / `get_thread` reload a waiting question. The checkpointer's `checkpoint*` tables are created by LangGraph's `setup()` at agent startup and are not managed by Alembic migrations. Subject-less threads exist only while the question waits (`threads.subject_ids` allows 0–3, migration 0007).

**May use (application layer only):** `knowledge` (the learner's subjects from their documents), `subjects` (names), `accounts`, `insights` (log declines). Everyone may use `shared`.

**Rules:** Never reads chunk tables: retrieval goes through the `Retriever` port (MCP client adapter). Threads store `subject_ids`, so renames never affect them. Document text is passed to the model as quoted data. Never imports `learning`.

Layout: `domain/` → `ports/` ← `application/`, `adapters/`. Other modules import only `tutoring.application`.
See `sdd/specs/2026-10-02-project-structure-design.md`.
