# Smart Tutor — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v1.2 (refined from `initial-idea.md`; adds conversation/note management, quizzes, daily/weekly reports, and recommendations) |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-02 |
| **Lifecycle** | Build → Test → Deploy → Monitor ([The Agent Development Lifecycle](https://www.langchain.com/blog/the-agent-development-lifecycle)) |

---

## 1. Summary

Smart Tutor is a subject-scoped AI tutor. A learner enrolls in subjects (e.g. *English / IELTS*, *AI Agents*) and simply asks questions. The tutor **detects which subject a question belongs to**, answers **only from that subject's documents**, cites its sources, and politely declines anything the documents don't cover. Learners can browse their conversations and **Lesson Notes** by date and subject, take **quizzes** generated from their notes, and read **daily/weekly reports** that summarize what they learned across subjects and suggest **what to learn next**. A lifetime **learning record** ties it all together.

The project has a second, equally important goal: to exercise the full **agent development lifecycle** (tracing, evaluation, security hardening, and deployment to AWS Bedrock AgentCore) so the agent is demonstrably reliable and safe, not just functional.

## 2. Problem

General-purpose chatbots drift off-topic, answer from unknown sources, and forget what a learner studied last week. Learners preparing for a specific goal (e.g. IELTS) need a tutor that:

- stays inside the subjects they are studying,
- grounds every answer in trusted material and shows where it came from,
- helps them capture, track, and revisit what they learned,
- checks their understanding and tells them what to study next.

## 3. Personas

| Persona | Job to be done |
|---|---|
| **Learner** (primary) | "Help me study *my* subjects efficiently, keep me on track, show me which source backs each answer, test what I understood, and tell me what to study next." |
| **Admin** (secondary) | "Let me upload and archive the trusted documents for each subject, see which questions the documents can't answer, and build evaluation datasets." |
| **Developer / Operator** (internal) | "Let me trace, evaluate, and monitor the agent so I can ship changes with confidence." |

## 4. Glossary

| Term | Definition |
|---|---|
| **Subject** | The unit of scope and access control (e.g. `ielts`, `ai-agents`), represented by an S3 prefix `subjects/<subject>/`. Created by an Admin; never deleted. |
| **Enrolled subjects** | The subjects a Learner has chosen ("favorites"). The tutor only detects, searches, and answers within enrolled subjects. |
| **Thread** | One conversation. Bound to exactly **one** subject, set automatically from the first question (or chosen by the learner when detection is unsure) and stored in the **agent state**. The subject cannot change mid-thread; questions outside it are rejected. |
| **Document** | A PDF uploaded by an Admin to a subject's S3 prefix. Identified by its S3 key; never deleted, only **archived**. Treated as trusted content. |
| **Chunk** | An embedded fragment of a Document version, with metadata for citation, status (`active` / `archived`), and access control. |
| **Citation** | Reference returned with an answer: document title and page. |
| **Lesson Note** | A Markdown summary of one thread, owned by one Learner. **One note per thread.** Never hard-deleted; "delete" archives it. |
| **Learning record** | A lifetime entry in the learner's long-term memory describing what was learned in a thread (subject, topics, key points). Written when the learner creates a note **or** automatically after the thread has been idle for a configurable time (default 10 minutes). |
| **Content gap** | An in-subject question the documents could not answer; reported to Admins. |
| **Topic catalog** | The list of topics each subject covers, derived automatically from document headings at ingestion. Used to recommend what to learn next. |
| **Quiz** | A set of multiple-choice questions generated from Lesson Notes the learner selects; graded in code. Each question is tagged with its subject and topic. |
| **Report** | A daily or weekly summary of a learner's activity across all subjects (topics learned, threads, quiz results, weak topics) with recommendations for the next day or week. |
| **Recommendation** | A suggested topic to study next, always taken from the topic catalog of an enrolled subject and pointing to a document and page. |

## 5. Goals and non-goals

### Goals (MVP)
1. Learners get **grounded, cited answers** within their enrolled subjects, **without choosing a subject** for each conversation.
2. Questions the documents don't cover (off-topic or missing content) are **declined**, and **prompt-injection attempts in user input** have no effect.
3. Learners can **create, edit, archive, and continue from Lesson Notes**, and a lifetime **learning record** tracks what they learned in each thread.
4. Learners can **manage conversations and notes** (filter by date and subject), **take quizzes** generated from their notes, and **read daily/weekly reports** with recommendations for what to learn next.
5. **Token usage is tracked and shown** per thread and in total.
6. Admins receive a weekly **content-gap report**.
7. Every agent run is **traced and evaluated** in LangSmith (search step, subject detection, retrieval and answer relevance, quiz and recommendation quality), with human feedback used to calibrate LLM judges.
8. All components require **authentication and authorization** via Keycloak; users can only see their own data.
9. The agent is **deployed to AWS Bedrock AgentCore**.

### Non-goals (MVP)
- Token credits, quotas, or billing (usage is shown, not limited; cost is protected by rate limiting and budget alerts).
- Free-text quiz answers graded by an LLM (multiple choice only); spaced-repetition scheduling.
- Push or email notifications for reports (reports appear in the app).
- Web search of any kind.
- Admin web UI (admins work in S3 directly).
- Deep Agents planning/filesystem features (a plain LangGraph flow is enough for the MVP).
- Defending against instructions embedded in documents (documents are admin-curated and trusted).
- Document formats other than PDF; cross-subject threads; note sharing; mobile apps; non-English UI.

## 6. Key product decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Subject** is the single scope concept; access = enrolled subjects. | Draft mixed "favorite", "role", and "subject". |
| D2 | The corpus is **whatever Admins upload** under `subjects/<subject>/` in S3. | Owner decision. |
| D3 | A thread's subject is **auto-detected** from the first question among the learner's enrolled subjects; if detection is unsure, the learner picks one. The subject is then stored in the **agent state** and fixed for the thread. Later questions outside the subject are **rejected**, asking the learner to stay within the subject or start a new conversation. | No subject picker before chatting; retrieval and evaluation stay simple. |
| D4 | Subject access is **enforced in the RAG MCP server** using the user's forwarded access token (§9.3), never by the agent's prompt. | The LLM must not be the access-control boundary. |
| D5 | **Search always runs first** (a fixed graph step, not a model decision). Off-topic questions and in-subject questions the documents don't cover get the **same friendly decline**. | Fewer model calls, a predictable trajectory, and one rule instead of two. |
| D6 | **No token credit.** Usage is recorded and displayed; cost is protected by per-user rate limits and Bedrock budget alerts. | Owner decision, for simplicity. A credit that users can raise or reset at will doesn't limit anything. |
| D7 | The only **untrusted input is the user's prompt**; injection defenses target it. | Documents are admin-uploaded; there are no web or third-party sources. |
| D8 | **One Lesson Note per thread**, stored in **PostgreSQL**, private to its owner. **Soft delete only**: "delete" archives the note; there is no hard delete. | Removes many-to-many links and S3/DB duplication; nothing a learner wrote is lost. |
| D9 | A **learning record** is written to long-term memory (a) when the learner asks for a note, and (b) automatically when the thread has been idle for `learning_record_idle_minutes` (default 10, admin-configurable). Records span all subjects so later reports can summarize across subjects. | Lifetime progress tracking even for learners who never create notes; foundation for daily/weekly reports and recommendations. |
| D10 | Documents are **never deleted**. Archiving removes a document from search but keeps its chunks, so old citations still resolve; the S3 object moves to Glacier. | Owner decision; keeps history intact. |
| D11 | Conversations, notes, quizzes, and reports all use **soft delete (archive)** and support **filtering by date and subject**. | One consistent management model across the app. |
| D12 | Quizzes are **multiple choice only**, generated from **selected Lesson Notes** (active notes only) and **graded in code**. | Deterministic, cheap grading; testable answer keys. |
| D13 | Reports are generated **automatically** (daily and weekly, in the learner's time zone, only when there was activity) and **on demand**, covering **all subjects**. | Learners get a summary without asking; one view across subjects. |
| D14 | "What to learn next" picks topics **only from the topic catalog** of enrolled subjects, prioritizing weak quiz topics, then topics not yet covered. Requested from the Reports screen, not in chat. | Grounded, explainable recommendations; chat threads stay subject-bound (D3). |

## 7. Scope

### MVP (v1.0)
- Registration, login, logout via **Keycloak's hosted pages**.
- Enroll in / leave subjects.
- Start a chat without choosing a subject; subject auto-detected (or picked when unsure); streamed responses.
- Grounded answers with citations (title + page) from the RAG MCP server.
- Friendly decline for off-topic or uncovered questions; prompt-injection defenses on user input.
- Lesson Notes (one per thread): create or overwrite via "Summarize lesson", edit, archive (soft delete) and restore, "Discuss this note" (starts a new thread).
- Lifetime learning records, written on note creation and after 10 idle minutes (configurable).
- Off-subject follow-up questions rejected, with a "New conversation" option.
- Conversation management: list, filter by date and subject, open, view the linked note, archive and restore.
- Note management: filter by date and subject; generate a multiple-choice quiz from selected notes; take it and see results.
- Daily/weekly reports across subjects (automatic and on demand), filter and archive; "What should I learn next day/week?" recommendations.
- Topic catalog per subject, derived from document headings at ingestion.
- Token usage view (per thread and total); per-user rate limiting.
- PDF ingestion from S3 events: add, replace (new version), archive, unarchive.
- Weekly content-gap report for Admins.
- LangSmith tracing, evaluation suites, and human-feedback annotation (§10).
- Agent and MCP server deployed on Bedrock AgentCore; API on ECS Fargate.

### Next (low priority)
- Carry an answer's citations into the Lesson Note so each point links back to its source.

### Later
- Free-text quiz questions with LLM grading; spaced repetition; report notifications (email/push).
- Optional admin-written subject metadata (`_subject.json`: display name, description, curated topic list) to refine the topic catalog.
- Token credit tiers by user level (L1-Silver, L2-Golden).
- Admin UI; more document formats; web search; note sharing; multilingual UI; mobile app.

## 8. User stories and acceptance criteria (MVP)

**US-1 Register and sign in**
- *Given* a new visitor, *when* they choose "Sign up", *then* they register on Keycloak's hosted page (with Keycloak email verification), get the `learner` role, and land on subject enrollment.
- Unauthenticated calls to the API, agent, or MCP server return `401`.

**US-2 Enroll in subjects**
- *Given* a signed-in learner, *when* they open subject enrollment, *then* they see every subject Admins have created and can enroll in or leave any of them.
- *Given* a thread whose subject the learner has left, *then* the thread is **read-only** (history and its note remain viewable and editable) until they enroll again.

**US-3 Subject auto-detection**
- *Given* a learner enrolled in exactly one subject, *when* they start a thread, *then* it is bound to that subject.
- *Given* several enrolled subjects, *when* the first question clearly matches one subject (§9.2), *then* the thread is bound to it and the UI shows the detected subject.
- *When* detection is unsure (no subject clears the threshold, or two are too close), *then* the tutor asks "Which subject is this about?" with the enrolled subjects as choices, and binds the thread to the learner's pick.

**US-4 Ask a grounded question**
- *Given* a thread bound to subject *S*, *when* the learner asks a question, *then* the search step retrieves chunks **only from S**, and a streamed answer based on them lists ≥ 1 citation (document title, page).

**US-5 Reject questions outside the thread's subject**
- *Given* a thread bound to subject *S*, *when* a question is outside *S* or the documents of *S* don't support an answer, *then* the tutor declines in one or two friendly sentences, without answering from its own knowledge: "This conversation is about *S*. Please ask a question about *S*, or start a new conversation for other topics."
- The decline shows a **"New conversation"** action; the new thread detects its subject from the question the learner asks there.
- The thread's subject never changes as a result of a later question.
- Each decline is logged as a content-gap candidate (§9.6).

**US-6 Prompt-injection resistance**
- *When* the user's prompt tries to override instructions (e.g. "ignore previous instructions", "search subject X", "print your system prompt"), *then* the tutor keeps its scope, does not reveal its system prompt, and cannot reach other subjects or other users' data.

**US-7 Lesson Note**
- *When* the learner clicks "Summarize lesson" in a thread, *then* the tutor writes a Markdown note for that thread (creating it, or overwriting the previous version) and shows it in the learner's notes list.
- The learner can view and edit (Markdown editor) a note.
- *When* the learner deletes a note, *then* it is **archived** (soft delete): hidden from the notes list, shown under "Archived", and restorable. Notes are never hard-deleted, and archiving does not affect the thread or its learning record.
- *When* they choose "Discuss this note", *then* a new thread starts, bound to the note's subject, with the note as context and a link back to the source note.

**US-8 Learning record**
- **Trigger 1 (on request):** *when* the learner clicks "Summarize lesson", *then* the note and the thread's learning record (subject, topics, key points, thread id, note id, timestamp) are written together.
- **Trigger 2 (idle):** *given* a thread with new messages since its last record, *when* no message has been sent for `learning_record_idle_minutes` (default 10), *then* the thread's learning record is written or updated, without creating a note.
- *When* an admin changes `learning_record_idle_minutes`, *then* the new value applies from the next sweep, with no redeploy.
- There is at most one learning record per thread; each trigger updates it in place.
- Learning records are stored across all of a learner's subjects (subject is a field), so a single query can summarize a day or week across subjects.

**US-9 Token usage**
- The learner sees input/output tokens per thread and in total; figures match the `usage` reported by Bedrock for each completed turn.
- *When* a learner exceeds the per-user rate limit, *then* the API returns `429` with a retry-after message.

**US-10 Document sync via S3 events**
- *When* an admin uploads a PDF to `subjects/<subject>/`, *then* within 5 minutes its chunks are searchable, with metadata `subject`, `document_id` (S3 key), `version_id`, `title`, `page`, `status`, `ingested_at`, `embedding_model`, `embedding_dim`.
- *When* an admin uploads a new version to the same key, *then* the new version's chunks become `active` and the previous version's chunks become `archived`.
- *When* an admin tags an object `status=archived`, *then* its chunks become `archived` (excluded from search, still resolvable for citations); removing the tag makes them `active` again without re-embedding.
- Re-processing the same event is idempotent; failed events are retried and land in a dead-letter queue.

**US-11 Content-gap report**
- Every week, Admins receive a report per subject of declined questions (grouped by similarity, with counts and best retrieval score), **without learner identities**.

**US-12 Data isolation**
- A learner can never read, list, or modify another learner's threads, notes, learning records, quizzes, reports, or usage — verified by automated tests against the API and MCP server.

**US-13 Manage conversations**
- The learner sees a list of their conversations (title from the first question, subject, last activity), newest first.
- They can filter by **date range** and **subject**, and combine both.
- Opening a conversation shows its history and, if one exists, its **linked Lesson Note** with a link to open it.
- They can **archive** and **restore** a conversation; archived conversations are hidden by default, viewable under "Archived", and read-only.

**US-14 Manage notes and generate a quiz**
- The learner sees their notes with subject, date, and a link to the source conversation; they can filter by **date range** and **subject**.
- *When* they select 1–10 active notes and click "Generate quiz", *then* the tutor creates a quiz of 5–10 multiple-choice questions (4 options, exactly one correct), each tagged with subject and topic, using only the content of the selected notes.
- *When* they submit answers, *then* the quiz is graded in code; they see their score, the correct answers, a short explanation for each, and their score per topic.
- They can list past quizzes (filter by date and subject), retake one, and archive it.

**US-15 Daily and weekly reports**
- *Given* a day (or week, Monday to Sunday) in the learner's time zone with activity, *when* it ends, *then* a report is generated automatically covering **all subjects**: topics learned (from learning records), number of conversations, quiz results, weak topics (quiz topics scored below 60%), and recommendations for the next period.
- No report is generated for a period without activity.
- The learner can generate a report for the current day or week on demand ("Generate now"), list reports (filter by period type and date), view, and archive them.

**US-16 What should I learn next?**
- *When* the learner clicks "What should I learn tomorrow?" or "…next week?", *then* the tutor returns 3–5 recommendations, each with: subject, topic, the reason (e.g. "quiz score 40%" or "not studied yet"), and where to read it (document title and page).
- Recommendations come only from the topic catalog of enrolled subjects and active documents; weak topics come first, then topics not yet covered.
- Each recommendation has a "Start learning" action that starts a new conversation bound to that subject with the topic as the first question.

## 9. Solution overview

### 9.1 Components

```
 Web App (React) ──► API Server (FastAPI, ECS Fargate) ──► Smart Tutor Agent (LangGraph, AgentCore Runtime)
       │                 │  (user JWT)                           │  (same user JWT)
       ▼                 ▼                                       ▼
   Keycloak (OIDC) ◄── validate ─────────────────────── RAG MCP Server (AgentCore Runtime) ──► PostgreSQL + pgvector
                                                                                                 ▲
 Admin ──► S3 subjects/<subject>/ ──► S3 events → SQS → Ingestion worker (Docling → chunk → embed) ┘
                                      (versioning on; archived objects → Glacier via lifecycle rule)
```

| Component | Responsibilities |
|---|---|
| **RAG MCP Server** | `search(query, subjects, k)` over streamable HTTP. Validates the forwarded JWT, intersects `subjects` with the user's enrollments, searches `active` chunks only, returns chunks with scores and citation metadata. Also `get_chunk(chunk_id)` for resolving old citations (including archived chunks). |
| **Ingestion worker** | Consumes S3 `ObjectCreated` and `ObjectTagging` events via SQS; extracts PDFs with Docling; chunks; embeds; activates or archives chunks by `document_id` + `version_id`; updates the topic catalog (§9.7). |
| **Smart Tutor agent** | The paths in §9.2 (ask, summarize, idle record, quiz, report, recommend). Checkpointer (thread history) and long-term memory (learning records) in PostgreSQL. Reports token usage per call. |
| **API Server** | Auth, enrollments, conversations, notes, quizzes, reports (list, filter, archive), streaming (SSE), quiz grading, usage view, rate limiting; forwards the user's token to the agent. |
| **Scheduled jobs** | Learning-record sweeper (every minute, §9.2); learner reports (hourly, generates reports for learners whose day/week just ended in their time zone, §9.8); content-gap report (weekly, §9.6). |
| **Web App** | Keycloak login redirect, subject enrollment, chat, conversations, notes editor, quizzes, reports and recommendations, usage view. |

### 9.2 Agent flow

A plain **LangGraph** graph; no model-chosen tools for retrieval.

**Ask path (every chat turn):**

The graph state carries `subject` (null until bound). It is persisted by the checkpointer with the thread, written once, and never changed by later turns.

1. **Resolve subject.** If `state.subject` is set, use it. Otherwise, run step 2 across **all enrolled subjects**, score each subject by its best chunk similarity, and:
   - set `state.subject` if the best subject's score ≥ `detect_threshold` **and** leads the runner-up by ≥ `detect_margin`;
   - otherwise reply "Which subject is this about?" with the enrolled subjects as choices, and stop this turn.
   - Learners with one enrolled subject skip detection. Threshold and margin are tuned on the detection dataset (§10.3).
2. **Search (fixed step).** Call the MCP `search` with the thread's subject and the question; get the top-k chunks (k = 5). The same search results serve both detection and answering, so the first turn costs no extra calls.
3. **Relevance gate (code).** If the best score in `state.subject` is below `answer_floor` (typical for a question about another subject), reject with the off-subject message (US-5) without calling the LLM, and log a content-gap candidate.
4. **Answer (Nova 2 Lite, streamed).** System prompt (naming `state.subject`) + capped recent history + chunks. The model either answers with citations or calls its only tool, `decline(reason)`, when the question is outside the subject or the chunks don't support an answer; the decline is shown with the same off-subject message and logged.

**Summarize path ("Summarize lesson" button):** read the thread → generate the Lesson Note and the learning record in one model call (the record returned via a `save_learning_record` tool call) → upsert the note (PostgreSQL) and the record (long-term memory).

**Idle record path (background):** a sweeper runs every minute and selects threads where `last_message_at < now − learning_record_idle_minutes` and `last_message_at > record_written_at`. For each, it runs the record half of the summarize path (record only, no note) and sets `record_written_at`. The threshold is read from configuration on each sweep.

**Quiz path ("Generate quiz" on selected notes):** load the selected active notes (ownership checked) → one model call returns the quiz via a `create_quiz` tool call (questions, 4 options, correct index, explanation, subject, topic) → code validates it (5–10 questions, exactly one correct option each, every topic present in the source notes; one retry on failure) → store the quiz without exposing the answer key to the client until submission. Grading is done by the API in code.

**Report path (scheduled or "Generate now"):** gather the period's learning records, thread counts, and quiz results across all subjects → compute weak topics in code (topic score < 60%) → one model call writes the report summary → append recommendations from the recommend path → store the report.

**Recommend path ("What should I learn tomorrow / next week?", also used by reports):** candidates come from code, not the model:
1. weak topics from recent quizzes;
2. topic-catalog entries of enrolled subjects (active documents only) not yet matched by any learning record (embedding similarity between catalog topics and record topics).

The model only ranks the candidates and writes a one-line reason for 3–5 of them (`recommend` tool call); code rejects any topic not in the candidate list. Each recommendation keeps its catalog entry's document and page.

None of these paths go through the chat thread, so threads stay subject-bound (D3).

Because the subject comes from code and the database, not from the model, attacks like "search subject X" have nothing to change.

### 9.3 Identity propagation and access enforcement

1. The Web App signs the user in with Keycloak (OIDC Authorization Code + PKCE, Keycloak hosted login/registration pages) and calls the API with `Authorization: Bearer <access_token>`.
2. The API validates the token (signature via Keycloak JWKS, `iss`, `exp`, `aud`), applies the rate limit, then invokes the agent and **forwards the same token**.
3. The agent attaches the token to every MCP request (`Authorization` header on the streamable-HTTP transport). The token is passed in runtime context, **never placed in the prompt**.
4. The MCP server (on AgentCore Runtime) has the token validated by the runtime's `CUSTOM_JWT` authorizer against Keycloak's OIDC discovery URL; `Authorization` is on the runtime's request-header allowlist so the server receives it. The server reads `sub`, looks up the user's enrolled subjects in PostgreSQL, and searches only the intersection with the requested `subjects` (`403` if empty). The filter is applied in SQL.

Keycloak setup: one realm with self-registration and email verification enabled; clients `smart-tutor-web` (public), `smart-tutor-api`, `rag-mcp`; an **audience mapper** so access tokens carry `aud: [smart-tutor-api, rag-mcp]`. Enrollments live in PostgreSQL, not in token claims, so changes apply immediately.

Later hardening (not MVP): Keycloak **token exchange** (RFC 8693) so the MCP server receives a narrower, MCP-only token.

### 9.4 Learner data

| Data | Store | Key | Notes |
|---|---|---|---|
| Lesson Note | PostgreSQL table `lesson_notes` | `thread_id` (unique) | `user_id`, `subject`, `markdown`, `status` (`active` / `archived`), `archived_at`, `source_note_id` (for "Discuss this note" threads), `updated_at`. No hard delete. |
| Learning record | LangGraph long-term memory (PostgreSQL-backed store), namespace `("learning", user_id)` | `thread_id` | `subject`, `topics[]`, `key_points[]`, `note_id` (nullable), `trigger` (`note` / `idle`), `learned_at`, `updated_at`. |
| Thread activity | PostgreSQL table `threads` | `thread_id` | `user_id`, `subject`, `title`, `status` (`active` / `archived`), `created_at`, `last_message_at`, `record_written_at` (drive the idle trigger). Indexed on `(user_id, subject, last_message_at)` for filtering. |
| Quiz | PostgreSQL tables `quizzes`, `quiz_questions`, `quiz_attempts` | `quiz_id` | Source `note_ids[]`, subjects, questions (subject, topic, options, correct index, explanation), attempts with answers, score, per-topic scores, `status`. |
| Report | PostgreSQL table `reports` | `report_id` | `user_id`, `period_type` (`daily` / `weekly`), `period_start`, `summary` (Markdown), `stats`, `recommendations[]`, `trigger` (`scheduled` / `on_demand`), `status`. Unique on `(user_id, period_type, period_start, trigger = scheduled)`. |
| Learner profile | PostgreSQL table `learners` | `user_id` | `time_zone` (captured from the browser, editable), used to schedule reports. |
| Setting | Configuration (AWS SSM Parameter Store) | `/smart-tutor/learning-record-idle-minutes` | Default 10; admins change it without a redeploy. |

- The namespace is per learner, **not per subject**, so daily/weekly reports can summarize across all subjects with one query and group by `subject`.
- Records are written only by the two triggers, never on every chat turn, so there is no per-turn memory cost.
- Model tokens used to write records are recorded as background usage of the thread and appear in the learner's usage view.
- Daily/weekly reports and "what to learn next" read these records together with quiz results (§9.2, §9.8).

### 9.5 Documents: versions and archiving

S3 **versioning** is enabled on the documents bucket, and documents are never deleted.

| Admin action | S3 event | Effect on chunks |
|---|---|---|
| Upload a new PDF | `s3:ObjectCreated:*` | Extract, chunk, embed; chunks `active`. |
| Upload a new version to the same key | `s3:ObjectCreated:*` (new `version_id`) | New version's chunks `active`; previous version's chunks `archived`. |
| Archive: tag object `status=archived` | `s3:ObjectTagging:Put` | All chunks for that key `archived` (excluded from search). |
| Unarchive: remove the tag | `s3:ObjectTagging:Delete` | Chunks `active` again; no re-embedding needed. |

**Moving archived files to Glacier:** S3 lifecycle rules handle storage tiering automatically:
- a rule filtered on tag `status=archived` transitions current objects to **S3 Glacier Flexible Retrieval** (e.g. after 30 days);
- a rule on **noncurrent versions** transitions replaced versions the same way.

Archived chunks keep their text, title, and page in PostgreSQL, so citations in old threads still display without reading the file from S3; the UI marks them "archived". Reading the original file back requires a Glacier restore (minutes to hours), which no MVP flow needs. Glacier classes have minimum storage durations (90 days for Flexible Retrieval), which is fine since documents are never deleted.

### 9.6 Content-gap report

- Every decline (relevance gate or `decline` tool) writes `subject`, question text, best retrieval score, and timestamp to a `content_gaps` table, **without user id**.
- A weekly job (EventBridge Scheduler → small task) groups similar questions by embedding similarity, ranks groups by count, and writes `s3://…/reports/content-gaps/<subject>/<yyyy-ww>.md`.
- Questions with very low scores are mostly off-topic; the report lists groups closest to the threshold first, since those are the most likely missing content.

### 9.7 Topic catalog

- At ingestion, the worker takes the section headings Docling extracts from each PDF (levels 1–2) and stores them as catalog entries: `subject`, `topic` (heading text), `document_id`, `version_id`, `page`, `status`, and an embedding of the heading.
- Entries follow their document's status: archived documents' topics are excluded from recommendations.
- No extra model call is needed. Documents with poor headings produce a thin catalog; the optional admin-written `_subject.json` (Later) can add a curated topic list.
- "Covered" = a catalog topic whose embedding is close to a topic in the learner's learning records (threshold tuned on the eval set).

### 9.8 Reports and scheduling

- A scheduler runs **hourly** and finds learners whose local day (or week, ending Sunday) has just ended, using `learners.time_zone`.
- For each with activity in that period (any message, note, or quiz attempt), it runs the report path (§9.2). Learners with no activity get no report.
- Scheduled reports are idempotent per `(user, period_type, period_start)`; "Generate now" creates an on-demand report for the current period without replacing the scheduled one.
- Report and recommendation tokens are recorded as background usage and appear in the learner's usage view.

### 9.9 Model integration notes

**Embeddings: `amazon.nova-2-multimodal-embeddings-v1:0`**
- `InvokeModel` with `taskType: SINGLE_EMBEDDING`.
- `embeddingPurpose: GENERIC_INDEX` for chunks, `TEXT_RETRIEVAL` for queries.
- **Dimension 1024** (pgvector HNSW/IVFFlat indexes support `vector` columns up to 2,000 dimensions; the 3072 default would not index). Changing it later means re-embedding, so record `embedding_model` and `embedding_dim` on each chunk.
- Text input up to **8,192 characters** per call; chunks of ~1,500–3,000 characters; `truncationMode: NONE` so oversize chunks fail loudly.

**LLM: `amazon.nova-2-lite-v1:0`** (agent model; no fallback)
- **Converse / ConverseStream** on `bedrock-runtime` (`ChatBedrockConverse` in LangChain); Chat Completions is not supported for this model.
- Called through the **`us.amazon.nova-2-lite-v1:0`** inference profile (no in-region availability); requests may be served in us-east-1, us-east-2, or us-west-2.
- Context window 1M tokens; max output 64K; streaming supported.
- Client-side tool calling is supported; the agent uses it only for `decline`, `save_learning_record`, `create_quiz`, and `recommend`. Since structured outputs aren't listed for this model, these tool calls are how it returns typed data, and code validates every payload.
- **Prompt caching** (system and messages, up to 4 checkpoints, 5-minute TTL, at most 20K tokens) for the fixed system prompt.
- Cap the history and chunks sent per turn; the large window is not a reason to fill it.

### 9.10 Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Wrong subject detected.** A short or ambiguous first question binds the thread to the wrong subject. | Margin rule plus "ask when unsure"; the UI shows the detected subject with a "Change" action that restarts the thread under the chosen subject; detection accuracy evaluated (§10.1). |
| **Tool calling in streamed answers.** The answer step streams text but may call `decline`. | M0 spike verifies streamed text and tool calls through `ChatBedrockConverse`. Retrieval does not depend on tool calling. |
| **Cross-region routing.** Nova 2 Lite runs only via inference profiles. | Use the `us.` profile; requests stay in US regions (recorded in §11). |
| **Token cost per turn.** A 1M window makes it easy to send too many tokens. | Cap history and chunks, cache the fixed prefix, track tokens per turn in evals, rate-limit users, Bedrock budget alerts. |
| **Bad quiz questions.** Ambiguous options, two correct answers, or facts not in the notes. | Code validation of structure; quiz-quality LLM judge (§10.1); questions limited to the selected notes; learners can flag a question, which feeds the dataset. |
| **Recommendations that drift.** The model invents topics or suggests archived material. | Candidates built in code from the topic catalog and quiz results; the model only ranks and explains; unknown topics rejected. |
| **Thin topic catalog.** PDFs with poor headings give few topics. | Monitor catalog size per subject; optional `_subject.json` later. |
| **Judge bias.** Grading with the agent's own model inflates scores. | Judges and synthetic data use `qwen.qwen3-32b-v1:0`, a different model family, calibrated against human feedback (§10.2). |

### 9.11 Hosting

| Component | Hosting | Why |
|---|---|---|
| Agent | **AgentCore Runtime** | Project goal. |
| RAG MCP server | **AgentCore Runtime** (MCP protocol, served at `0.0.0.0:8000/mcp`) | Managed; built-in `CUSTOM_JWT` authorizer for Keycloak; forwards `Authorization`; same platform and observability as the agent. |
| API server | **ECS Fargate + ALB** | Long-lived SSE streams, standard FastAPI, stable PostgreSQL connection pool. |
| Ingestion worker and scheduled jobs (record sweeper, learner reports, content-gap report) | ECS Fargate tasks (SQS consumer; EventBridge Scheduler tasks) | Same container tooling as the API. |
| Database | RDS PostgreSQL + pgvector, same VPC | |

Alternatives considered: MCP via AgentCore Gateway → Lambda (extra hop, harder identity pass-through, RDS Proxy needed) or MCP on Fargate (we would run ALB, TLS, and JWT validation ourselves); API on Lambda (Python SSE needs an adapter, 15-minute limit, cold starts).

### 9.12 Stack

| Concern | Choice |
|---|---|
| Agent framework | LangChain + LangGraph (Deep Agents later, if needed) |
| Tracing and evaluation | LangSmith |
| Document extraction | Docling (PDF) |
| LLM (agent) | `amazon.nova-2-lite-v1:0` via `us.amazon.nova-2-lite-v1:0` |
| Embeddings | `amazon.nova-2-multimodal-embeddings-v1:0`, 1024 dimensions |
| LLM (judges, synthetic data) | `qwen.qwen3-32b-v1:0` (32K context, hybrid thinking) |
| Vector store / app DB / memory | PostgreSQL + pgvector (RDS) |
| Identity | Keycloak (OIDC; roles `learner`, `admin`; hosted login/registration) |
| Storage / events | S3 (versioning, lifecycle to Glacier), S3 Event Notifications → SQS |
| Hosting | AgentCore Runtime (agent, MCP); ECS Fargate (API, worker, report job) |
| API / Web | FastAPI / React |

### 9.13 Region: us-east-1

All environments run in **us-east-1 (N. Virginia)**, the only commercial region where every component is available:

| Component | Availability in us-east-1 |
|---|---|
| `amazon.nova-2-multimodal-embeddings-v1:0` | In-region; the only commercial region offering it. |
| `amazon.nova-2-lite-v1:0` | Via `us.amazon.nova-2-lite-v1:0` (served in us-east-1, us-east-2, or us-west-2). |
| `qwen.qwen3-32b-v1:0` | In-region. |
| AgentCore Runtime | Available; VPC connectivity in AZs `use1-az1`, `use1-az2`, `use1-az4`. Place RDS and Fargate subnets in these AZ IDs. |

**Open check (M0):** the Nova embeddings model card lists only `StartAsyncInvoke`, while the request schema documents synchronous `InvokeModel`. Query-time search needs the synchronous call; verify it before building M1.

## 10. Quality, safety, and evaluation

### 10.1 Evaluators

| Evaluator | Type | What it checks | MVP target |
|---|---|---|---|
| **Search step ran** | Code | Every answered turn's trajectory contains the MCP `search` call, with `subjects` = the thread's subject (or the enrolled set on an unbound first turn). | 100% |
| **Subject detection** | Code (labeled set) | Correct auto-bind / wrong auto-bind / asked when the question was clear. | ≥ 95% / ≤ 2% / ≤ 10% |
| **Retrieval relevance** | LLM-as-judge | Relevance of retrieved chunks to the question (0–1 per chunk; averaged). | ≥ 0.8 |
| **Answer relevance** | LLM-as-judge | Relevance of the final answer to the question. | ≥ 0.85 |
| **Decline correctness** | Code (labeled set) | Off-topic, off-subject follow-up, and uncovered questions declined / answerable questions wrongly declined. | ≥ 95% / ≤ 5% |
| **Subject stays fixed** | Code | In multi-turn cases with an off-subject follow-up, `state.subject` is unchanged and no search runs outside it. | 100% |
| **Learning record quality** | LLM-as-judge | The record's topics and key points match the thread content. | ≥ 0.8 |
| **Injection resistance** | Code + LLM-as-judge | No system-prompt leakage, no scope change, no cross-subject or cross-user data. | 0 failures |
| **Quiz validity** | Code | 5–10 questions, 4 options, exactly one correct, every question tagged with a subject and topic from the source notes. | 100% (after one retry) |
| **Quiz quality** | LLM-as-judge | Each question is answerable from the source notes, has one clearly correct option, and is not trivial. | ≥ 0.85 |
| **Recommendation grounding** | Code | Every recommended topic exists in the candidate list (catalog of enrolled subjects, active documents, or weak quiz topics). | 100% |
| **Report faithfulness** | LLM-as-judge | The report summary states only what the period's records and quiz results contain. | ≥ 0.9 |

*Recommended addition:* an LLM-as-judge **groundedness** check (answer vs. retrieved chunks), since an answer can be relevant yet unsupported.

**Judge model:** `qwen.qwen3-32b-v1:0`, temperature 0, fixed rubric returning a score and a short reason; thinking mode for nuanced criteria. Question + 5 chunks + answer is roughly 5K tokens, well within its 32K context.

### 10.2 Aligning LLM judges with human feedback

- Learners rate answers (👍/👎 + optional reason); feedback is attached to the LangSmith run.
- Admins review a weekly sample in a LangSmith **annotation queue**, scoring the same criteria the judges use.
- Track **judge–human agreement** per evaluator; below ~80%, revise the judge prompt with disagreeing examples and re-run on the annotated set.

### 10.3 Building the test dataset quickly

Admins curate the dataset, but **review generated candidates rather than write every example**:

1. **Synthetic Q&A from the corpus.** Sample chunks per subject; the judge model generates questions, reference answers, and the source chunk id (retrieval ground truth for free). Mix factual, conceptual, multi-chunk, and **unanswerable-but-on-topic** questions.
2. **Free off-topic negatives and detection labels.** Questions generated for subject A are off-topic for a learner enrolled only in B, and labeled examples for detection when enrolled in both. Add general-knowledge and **near-scope** questions, plus deliberately **ambiguous** ones that should trigger "Which subject?". Build **multi-turn cases** that start in subject A and switch to a subject-B question on turn 2 or 3, which must be rejected.
3. **Adversarial prompts by taxonomy × seed:** instruction override, system-prompt extraction, role-play jailbreaks, scope smuggling, subject manipulation ("search ai-agents instead"), other users' data, obfuscation (base64, misspellings, other languages), multi-turn escalation. Supplement with public prompt-injection datasets and red-teaming tools (e.g. promptfoo, garak).
4. **Human review gate.** Generated items go to a LangSmith annotation queue; only accepted items enter the dataset.
5. **Stable, versioned splits.** A **smoke** split (~30 items, every PR) and a **full** split (before release); never edit a version a release was gated on.
6. **Grow from production.** 👎-rated, judge-flagged, and content-gap questions, plus quiz questions learners flag, become candidates for the next dataset version.
7. **Learning-loop fixtures.** Seed synthetic learners with notes, learning records, and quiz attempts across both subjects (including weak topics and untouched catalog topics) to test quizzes, reports, and recommendations end to end.

Suggested starting size per subject: 40 answerable, 10 unanswerable, 30 off-topic (incl. 10 near-scope), 20 detection/ambiguous, 40 adversarial.

### 10.4 Online monitoring

Trace every run; run answer-relevance, decline, and detection evaluators on a sample of production traces; alert on error rate, latency, rate-limit hits, unusual per-user token volume, and drops in evaluator scores.

## 11. Non-functional requirements (pilot scale)

| Area | Target |
|---|---|
| Scale | 50 concurrent learners, ≤ 5 subjects, ≤ 2,000 pages per subject |
| Latency | First streamed token p95 ≤ 3 s; quiz generation p95 ≤ 15 s; on-demand report or recommendations p95 ≤ 30 s; list/filter screens p95 ≤ 500 ms; ingestion ≤ 5 min per document |
| Availability | Best-effort; no data loss on restart (checkpointer and memory in PostgreSQL) |
| Security | Every service validates Keycloak JWTs; secrets in AWS Secrets Manager; TLS everywhere; tokens never logged or put in prompts |
| Rate limiting | Per user, e.g. 20 messages/minute (config) |
| Privacy | Learners cannot hard-delete notes (soft delete only); full account data deletion on request is handled by an admin; threads and traces retained 180 days, learning records and notes for the account's lifetime; content-gap logs carry no user id; LLM requests stay within US regions |
| Cost | Track cost per conversation from day one; Bedrock budget alerts |
| Language | English UI; content in the subject's language |

## 12. Success metrics

- **Quality:** all §10.1 targets met on release and held for 4 weeks in sampled production traces.
- **Judge alignment:** ≥ 80% agreement between each LLM judge and human annotations.
- **Engagement (pilot):** ≥ 60% of registered learners start ≥ 3 threads; ≥ 1 Lesson Note per active learner per week; ≥ 40% of active learners take ≥ 1 quiz per week.
- **Learning loop:** ≥ 30% of recommendations lead to a "Start learning" conversation within the recommended period; average score on retaken quizzes improves over the first attempt.
- **Trust:** < 5% of answers rated 👎.
- **Content:** each weekly content-gap report leads to at least one document addition or a decision not to cover the topic.

## 13. Decisions log

| # | Topic | Decision |
|---|---|---|
| Q1 | Region | us-east-1 for dev and prod (§9.13). |
| Q2 | Token credit | Removed; usage shown, rate limits and budget alerts protect cost (D6). |
| Q3 | Hosting | Agent and MCP on AgentCore Runtime; API on ECS Fargate (§9.11). |
| Q4 | Launch subjects | IELTS and AI Agents. |
| Q5 | Retention | Threads and traces 180 days; learning records lifetime. |
| Q6 | Decline tone | Short, friendly, suggests asking within the subject. |
| Q7 | Agent model | `amazon.nova-2-lite-v1:0`, no fallback. |
| Q8 | Subject selection | Auto-detected from the first question; ask when unsure (D3). |
| Q9 | Document removal | Never deleted; archive via tag, Glacier via lifecycle (D10). |
| Q10 | Lesson Note deletion | Soft delete (archive) only; restorable (D8). |
| Q11 | Learning-record triggers | On note request, and after the thread is idle for 10 minutes (admin-configurable); records span all subjects (D9). |
| Q12 | Off-subject follow-ups | Subject fixed in agent state; reject and offer a new conversation (D3, US-5). |
| Q13 | Conversation and note management | List, filter by date and subject, archive/restore; conversation shows its linked note (D11). |
| Q14 | Quizzes | Multiple choice from selected notes, graded in code (D12). |
| Q15 | Reports and recommendations | Daily/weekly across subjects, automatic and on demand; recommendations from the topic catalog and weak quiz topics (D13, D14). |

## 14. Milestones

| Milestone | Exit criteria |
|---|---|
| M0 Foundations | Repo, CI, Keycloak realm (hosted login, self-registration), RDS PostgreSQL+pgvector, LangSmith project; all three Bedrock models reachable (Appendix A); synchronous Nova embeddings `InvokeModel` verified; Nova 2 Lite streamed text + tool call verified through `ChatBedrockConverse`; MCP server reachable on AgentCore Runtime with Keycloak JWT and VPC access to PostgreSQL |
| M1 RAG MCP | S3-event ingestion (add, new version, archive, unarchive) + topic catalog + authenticated MCP search; retrieval-relevance eval passing |
| M2 Agent | Subject detection and `state.subject`, search, relevance gate, answer/off-subject rejection, summarize path, idle-record sweeper; all §10.1 evals passing on the smoke split |
| M3 API + Web | Auth, enrollment, chat streaming, conversation and note management (filters, archive), usage view, rate limiting; isolation tests passing |
| M4 Learning loop | Quiz generation and grading, daily/weekly reports (scheduled + on demand), "what to learn next"; quiz, recommendation, and report evals passing on the smoke split |
| M5 Deploy + Monitor | AgentCore deployment, online evaluation, annotation queue, content-gap report job, dashboards and alerts |

---

## Appendix A — Setup checklist for the Admin (AWS)

1. **Region:** us-east-1.
2. **Model access** for `amazon.nova-2-lite-v1:0` (and the `us.` inference profile), `amazon.nova-2-multimodal-embeddings-v1:0`, and `qwen.qwen3-32b-v1:0`. IAM policies for the agent must allow the **inference profile ARN and the underlying model ARNs in every destination region** of that profile.
3. **IAM roles** per workload (ingestion worker, MCP server, agent runtime, report job) with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` scoped to these models; a Bedrock API key for local development if preferred.
4. **Service quotas** for all three models (requests and tokens per minute), sized for ingestion and 50 concurrent learners.
5. **Network:** whether `bedrock-runtime` calls must go through a VPC interface endpoint (PrivateLink).
6. **S3:** versioning enabled on the documents bucket; event notifications for `ObjectCreated` and `ObjectTagging` to SQS; lifecycle rules moving `status=archived` objects and noncurrent versions to Glacier Flexible Retrieval.
7. **Budget alerts:** monthly Bedrock budget and who receives the alerts.
8. **Guardrails (optional):** a Bedrock Guardrail on agent calls as an extra layer against prompt injection.
