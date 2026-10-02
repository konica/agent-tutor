# Smart Tutor — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v1.1 (refined from `initial-idea.md`; simplified scope; note soft delete, learning-record triggers, subject in agent state) |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-02 |
| **Lifecycle** | Build → Test → Deploy → Monitor ([The Agent Development Lifecycle](https://www.langchain.com/blog/the-agent-development-lifecycle)) |

---

## 1. Summary

Smart Tutor is a subject-scoped AI tutor. A learner enrolls in subjects (e.g. *English / IELTS*, *AI Agents*) and simply asks questions. The tutor **detects which subject a question belongs to**, answers **only from that subject's documents**, cites its sources, and politely declines anything the documents don't cover. Learners can turn a conversation into a **Lesson Note**, and the tutor keeps a lifetime **learning record** that will later power progress reports and "what to learn next" suggestions.

The project has a second, equally important goal: to exercise the full **agent development lifecycle** (tracing, evaluation, security hardening, and deployment to AWS Bedrock AgentCore) so the agent is demonstrably reliable and safe, not just functional.

## 2. Problem

General-purpose chatbots drift off-topic, answer from unknown sources, and forget what a learner studied last week. Learners preparing for a specific goal (e.g. IELTS) need a tutor that:

- stays inside the subjects they are studying,
- grounds every answer in trusted material and shows where it came from,
- helps them capture, track, and revisit what they learned.

## 3. Personas

| Persona | Job to be done |
|---|---|
| **Learner** (primary) | "Help me study *my* subjects efficiently, keep me on track, and show me which source backs each answer." |
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

## 5. Goals and non-goals

### Goals (MVP)
1. Learners get **grounded, cited answers** within their enrolled subjects, **without choosing a subject** for each conversation.
2. Questions the documents don't cover (off-topic or missing content) are **declined**, and **prompt-injection attempts in user input** have no effect.
3. Learners can **create, edit, archive, and continue from Lesson Notes**, and a lifetime **learning record** tracks what they learned in each thread.
4. **Token usage is tracked and shown** per thread and in total.
5. Admins receive a weekly **content-gap report**.
6. Every agent run is **traced and evaluated** in LangSmith (search step, subject detection, retrieval relevance, answer relevance), with human feedback used to calibrate LLM judges.
7. All components require **authentication and authorization** via Keycloak; users can only see their own data.
8. The agent is **deployed to AWS Bedrock AgentCore**.

### Non-goals (MVP)
- Token credits, quotas, or billing (usage is shown, not limited; cost is protected by rate limiting and budget alerts).
- Daily/weekly learning reports and "what to learn next" recommendations (the learning record is captured now; reports come later).
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
- Token usage view (per thread and total); per-user rate limiting.
- PDF ingestion from S3 events: add, replace (new version), archive, unarchive.
- Weekly content-gap report for Admins.
- LangSmith tracing, evaluation suites, and human-feedback annotation (§10).
- Agent and MCP server deployed on Bedrock AgentCore; API on ECS Fargate.

### Next (low priority)
- Carry an answer's citations into the Lesson Note so each point links back to its source.

### Later
- Daily/weekly learning reports and "what to learn next" recommendations from the learning record.
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
- A learner can never read, list, or modify another learner's threads, notes, learning records, or usage — verified by automated tests against the API and MCP server.

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
| **Ingestion worker** | Consumes S3 `ObjectCreated` and `ObjectTagging` events via SQS; extracts PDFs with Docling; chunks; embeds; activates or archives chunks by `document_id` + `version_id`. |
| **Smart Tutor agent** | The fixed flow in §9.2. Checkpointer (thread history) and long-term memory (learning records) in PostgreSQL. Reports token usage per turn. |
| **API Server** | Auth, enrollments, threads, streaming (SSE), notes CRUD, usage view, rate limiting; forwards the user's token to the agent. |
| **Report job** | Weekly scheduled task that builds the content-gap report (§9.6). |
| **Learning-record sweeper** | Scheduled every minute; writes learning records for threads idle longer than the configured time (§9.2). |
| **Web App** | Keycloak login redirect, subject enrollment, chat, notes editor, usage view. |

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

Because the subject comes from code and the database, not from the model, attacks like "search subject X" have nothing to change.

### 9.3 Identity propagation and access enforcement

1. The Web App signs the user in with Keycloak (OIDC Authorization Code + PKCE, Keycloak hosted login/registration pages) and calls the API with `Authorization: Bearer <access_token>`.
2. The API validates the token (signature via Keycloak JWKS, `iss`, `exp`, `aud`), applies the rate limit, then invokes the agent and **forwards the same token**.
3. The agent attaches the token to every MCP request (`Authorization` header on the streamable-HTTP transport). The token is passed in runtime context, **never placed in the prompt**.
4. The MCP server (on AgentCore Runtime) has the token validated by the runtime's `CUSTOM_JWT` authorizer against Keycloak's OIDC discovery URL; `Authorization` is on the runtime's request-header allowlist so the server receives it. The server reads `sub`, looks up the user's enrolled subjects in PostgreSQL, and searches only the intersection with the requested `subjects` (`403` if empty). The filter is applied in SQL.

Keycloak setup: one realm with self-registration and email verification enabled; clients `smart-tutor-web` (public), `smart-tutor-api`, `rag-mcp`; an **audience mapper** so access tokens carry `aud: [smart-tutor-api, rag-mcp]`. Enrollments live in PostgreSQL, not in token claims, so changes apply immediately.

Later hardening (not MVP): Keycloak **token exchange** (RFC 8693) so the MCP server receives a narrower, MCP-only token.

### 9.4 Lesson Notes and learning records

| Data | Store | Key | Notes |
|---|---|---|---|
| Lesson Note | PostgreSQL table `lesson_notes` | `thread_id` (unique) | `user_id`, `subject`, `markdown`, `status` (`active` / `archived`), `archived_at`, `source_note_id` (for "Discuss this note" threads), `updated_at`. No hard delete. |
| Learning record | LangGraph long-term memory (PostgreSQL-backed store), namespace `("learning", user_id)` | `thread_id` | `subject`, `topics[]`, `key_points[]`, `note_id` (nullable), `trigger` (`note` / `idle`), `learned_at`, `updated_at`. |
| Thread activity | PostgreSQL table `threads` | `thread_id` | `last_message_at`, `record_written_at` (drive the idle trigger). |
| Setting | Configuration (AWS SSM Parameter Store) | `/smart-tutor/learning-record-idle-minutes` | Default 10; admins change it without a redeploy. |

- The namespace is per learner, **not per subject**, so daily/weekly reports can summarize across all subjects with one query and group by `subject`.
- Records are written only by the two triggers, never on every chat turn, so there is no per-turn memory cost.
- Model tokens used to write records are recorded as background usage of the thread and appear in the learner's usage view.
- Daily/weekly reports and "what to learn next" read these records later.

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

### 9.7 Model integration notes

**Embeddings: `amazon.nova-2-multimodal-embeddings-v1:0`**
- `InvokeModel` with `taskType: SINGLE_EMBEDDING`.
- `embeddingPurpose: GENERIC_INDEX` for chunks, `TEXT_RETRIEVAL` for queries.
- **Dimension 1024** (pgvector HNSW/IVFFlat indexes support `vector` columns up to 2,000 dimensions; the 3072 default would not index). Changing it later means re-embedding, so record `embedding_model` and `embedding_dim` on each chunk.
- Text input up to **8,192 characters** per call; chunks of ~1,500–3,000 characters; `truncationMode: NONE` so oversize chunks fail loudly.

**LLM: `amazon.nova-2-lite-v1:0`** (agent model; no fallback)
- **Converse / ConverseStream** on `bedrock-runtime` (`ChatBedrockConverse` in LangChain); Chat Completions is not supported for this model.
- Called through the **`us.amazon.nova-2-lite-v1:0`** inference profile (no in-region availability); requests may be served in us-east-1, us-east-2, or us-west-2.
- Context window 1M tokens; max output 64K; streaming supported.
- Client-side tool calling is supported; the agent uses it only for `decline` and `save_learning_record`.
- **Prompt caching** (system and messages, up to 4 checkpoints, 5-minute TTL, at most 20K tokens) for the fixed system prompt.
- Cap the history and chunks sent per turn; the large window is not a reason to fill it.

### 9.8 Risks and mitigations

| Risk | Mitigation |
|---|---|
| **Wrong subject detected.** A short or ambiguous first question binds the thread to the wrong subject. | Margin rule plus "ask when unsure"; the UI shows the detected subject with a "Change" action that restarts the thread under the chosen subject; detection accuracy evaluated (§10.1). |
| **Tool calling in streamed answers.** The answer step streams text but may call `decline`. | M0 spike verifies streamed text and tool calls through `ChatBedrockConverse`. Retrieval does not depend on tool calling. |
| **Cross-region routing.** Nova 2 Lite runs only via inference profiles. | Use the `us.` profile; requests stay in US regions (recorded in §11). |
| **Token cost per turn.** A 1M window makes it easy to send too many tokens. | Cap history and chunks, cache the fixed prefix, track tokens per turn in evals, rate-limit users, Bedrock budget alerts. |
| **Judge bias.** Grading with the agent's own model inflates scores. | Judges and synthetic data use `qwen.qwen3-32b-v1:0`, a different model family, calibrated against human feedback (§10.2). |

### 9.9 Hosting

| Component | Hosting | Why |
|---|---|---|
| Agent | **AgentCore Runtime** | Project goal. |
| RAG MCP server | **AgentCore Runtime** (MCP protocol, served at `0.0.0.0:8000/mcp`) | Managed; built-in `CUSTOM_JWT` authorizer for Keycloak; forwards `Authorization`; same platform and observability as the agent. |
| API server | **ECS Fargate + ALB** | Long-lived SSE streams, standard FastAPI, stable PostgreSQL connection pool. |
| Ingestion worker, report job, learning-record sweeper | ECS Fargate tasks (SQS consumer; EventBridge Scheduler tasks) | Same container tooling as the API. |
| Database | RDS PostgreSQL + pgvector, same VPC | |

Alternatives considered: MCP via AgentCore Gateway → Lambda (extra hop, harder identity pass-through, RDS Proxy needed) or MCP on Fargate (we would run ALB, TLS, and JWT validation ourselves); API on Lambda (Python SSE needs an adapter, 15-minute limit, cold starts).

### 9.10 Stack

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

### 9.11 Region: us-east-1

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
6. **Grow from production.** 👎-rated, judge-flagged, and content-gap questions become candidates for the next dataset version.

Suggested starting size per subject: 40 answerable, 10 unanswerable, 30 off-topic (incl. 10 near-scope), 20 detection/ambiguous, 40 adversarial.

### 10.4 Online monitoring

Trace every run; run answer-relevance, decline, and detection evaluators on a sample of production traces; alert on error rate, latency, rate-limit hits, unusual per-user token volume, and drops in evaluator scores.

## 11. Non-functional requirements (pilot scale)

| Area | Target |
|---|---|
| Scale | 50 concurrent learners, ≤ 5 subjects, ≤ 2,000 pages per subject |
| Latency | First streamed token p95 ≤ 3 s; ingestion ≤ 5 min per document |
| Availability | Best-effort; no data loss on restart (checkpointer and memory in PostgreSQL) |
| Security | Every service validates Keycloak JWTs; secrets in AWS Secrets Manager; TLS everywhere; tokens never logged or put in prompts |
| Rate limiting | Per user, e.g. 20 messages/minute (config) |
| Privacy | Learners cannot hard-delete notes (soft delete only); full account data deletion on request is handled by an admin; threads and traces retained 180 days, learning records and notes for the account's lifetime; content-gap logs carry no user id; LLM requests stay within US regions |
| Cost | Track cost per conversation from day one; Bedrock budget alerts |
| Language | English UI; content in the subject's language |

## 12. Success metrics

- **Quality:** all §10.1 targets met on release and held for 4 weeks in sampled production traces.
- **Judge alignment:** ≥ 80% agreement between each LLM judge and human annotations.
- **Engagement (pilot):** ≥ 60% of registered learners start ≥ 3 threads; ≥ 1 Lesson Note per active learner per week.
- **Trust:** < 5% of answers rated 👎.
- **Content:** each weekly content-gap report leads to at least one document addition or a decision not to cover the topic.

## 13. Decisions log

| # | Topic | Decision |
|---|---|---|
| Q1 | Region | us-east-1 for dev and prod (§9.11). |
| Q2 | Token credit | Removed; usage shown, rate limits and budget alerts protect cost (D6). |
| Q3 | Hosting | Agent and MCP on AgentCore Runtime; API on ECS Fargate (§9.9). |
| Q4 | Launch subjects | IELTS and AI Agents. |
| Q5 | Retention | Threads and traces 180 days; learning records lifetime. |
| Q6 | Decline tone | Short, friendly, suggests asking within the subject. |
| Q7 | Agent model | `amazon.nova-2-lite-v1:0`, no fallback. |
| Q8 | Subject selection | Auto-detected from the first question; ask when unsure (D3). |
| Q9 | Document removal | Never deleted; archive via tag, Glacier via lifecycle (D10). |
| Q10 | Lesson Note deletion | Soft delete (archive) only; restorable (D8). |
| Q11 | Learning-record triggers | On note request, and after the thread is idle for 10 minutes (admin-configurable); records span all subjects (D9). |
| Q12 | Off-subject follow-ups | Subject fixed in agent state; reject and offer a new conversation (D3, US-5). |

## 14. Milestones

| Milestone | Exit criteria |
|---|---|
| M0 Foundations | Repo, CI, Keycloak realm (hosted login, self-registration), RDS PostgreSQL+pgvector, LangSmith project; all three Bedrock models reachable (Appendix A); synchronous Nova embeddings `InvokeModel` verified; Nova 2 Lite streamed text + tool call verified through `ChatBedrockConverse`; MCP server reachable on AgentCore Runtime with Keycloak JWT and VPC access to PostgreSQL |
| M1 RAG MCP | S3-event ingestion (add, new version, archive, unarchive) + authenticated MCP search; retrieval-relevance eval passing |
| M2 Agent | Subject detection and `state.subject`, search, relevance gate, answer/off-subject rejection, summarize path, idle-record sweeper; all §10.1 evals passing on the smoke split |
| M3 API + Web | Auth, enrollment, chat streaming, notes, usage view, rate limiting; isolation tests passing |
| M4 Deploy + Monitor | AgentCore deployment, online evaluation, annotation queue, content-gap report job, dashboards and alerts |

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
