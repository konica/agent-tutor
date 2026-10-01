# Smart Tutor — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v0.2 (refined from `initial-idea.md`) |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-01 |
| **Lifecycle** | Build → Test → Deploy → Monitor ([The Agent Development Lifecycle](https://www.langchain.com/blog/the-agent-development-lifecycle)) |

---

## 1. Summary

Smart Tutor is a subject-scoped AI tutor. A learner picks a subject (e.g. *English / IELTS*, *AI Agents*) and chats with an agent that answers **only from that subject's curated documents**, cites its sources, and politely refuses off-topic questions. Learners can turn a conversation into a **Lesson Note**, refine it later, and see how many tokens they are using.

The project has a second, equally important goal: to exercise the full **agent development lifecycle** — tracing, offline/online evaluation, security hardening, and deployment to AWS Bedrock AgentCore — so the agent is demonstrably reliable and safe, not just functional.

## 2. Problem

General-purpose chatbots drift off-topic, answer from unknown sources, and forget what a learner studied last week. Learners preparing for a specific goal (e.g. IELTS) need a tutor that:

- stays inside the subject they are studying,
- grounds every answer in trusted material and shows where it came from,
- helps them capture and revisit what they learned.

## 3. Personas

| Persona | Job to be done |
|---|---|
| **Learner** (primary) | "Help me study *my* subject efficiently, keep me on track, and show me which source backs each answer." |
| **Admin** (secondary) | "Let me curate the trusted documents for each subject and know they are indexed correctly." |
| **Developer / Operator** (internal) | "Let me trace, evaluate, and monitor the agent so I can ship changes with confidence." |

## 4. Glossary

| Term | Definition |
|---|---|
| **Subject** | The unit of scope and access control (e.g. `ielts`, `ai-agents`). Created by an Admin; never deleted. *Replaces "favorite" and "role" in the original draft.* |
| **Enrolled subjects** | The subjects a Learner has chosen. A Learner may only chat about, and retrieve from, enrolled subjects. |
| **Thread** | One conversation. Bound to exactly **one** subject at creation; the subject cannot change mid-thread. |
| **Document** | A source file (PDF, DOCX, …) uploaded by an Admin under a subject. |
| **Chunk** | An embedded fragment of a Document, with metadata for citation and access control. |
| **Citation** | Reference returned with an answer: document title, page/section, and chunk id. |
| **Lesson Note** | A Markdown summary of what was learned in one or more threads, owned by one Learner. *Replaces "take keynote".* |

## 5. Goals and non-goals

### Goals (MVP)
1. Learners get **grounded, cited answers** scoped to an enrolled subject.
2. **Off-topic and prompt-injection attempts are rejected** reliably.
3. Learners can **create, update, edit, delete, and continue from Lesson Notes**.
4. **Token usage is tracked** per user and per thread and visible to the learner.
5. Every agent run is **traced and evaluated** in LangSmith (retrieval, trajectory, final answer).
6. All components require **authentication and authorization** via Keycloak; users can only see their own data.
7. The agent is **deployed to AWS Bedrock AgentCore**.

### Non-goals (MVP)
- Web search (deferred — see §7).
- Hard token quotas / billing (tracking only).
- Admin web UI (admins upload to S3 directly).
- Cross-subject conversations, sharing notes with others, mobile apps, non-English UI.

## 6. Key product decisions

These resolve contradictions in the original draft. Revisit only with a reason.

| # | Decision | Rationale |
|---|---|---|
| D1 | **Subject** is the single scope concept; access = enrolled subjects. | Draft mixed "favorite", "role", and "subject". |
| D2 | Corpus is **per-subject, admin-curated documents**. The "two books" are the seed corpus (one per initial subject). | Draft said both "two books" and "documents per subject". |
| D3 | A thread is bound to **one subject**; switching subject starts a new thread. | Keeps retrieval filters and evaluation simple. |
| D4 | Subject scope is **enforced server-side in the RAG MCP server** from the caller's token, not by the agent's prompt. | The LLM must never be the access-control boundary. |
| D5 | If the corpus cannot support an answer, the agent says so rather than guessing. **No web fallback in MVP.** | Preserves groundedness; web search reintroduces off-scope and injection risk. |
| D6 | "Manage token usage" = **record and display** in MVP; per-user quotas in v1.1. | Smallest useful step; quotas need policy decisions (§13). |
| D7 | Lesson Notes are **private to their owner**; stored as Markdown in S3 with metadata in PostgreSQL. | Data ownership requirement. |

## 7. Scope

### MVP (v1.0)
- Learner registration, login, logout (Keycloak).
- Choose / change enrolled subjects from the admin-created list.
- Chat in a subject-bound thread with streamed responses.
- Grounded answers with citations from the RAG MCP server.
- Off-topic rejection and prompt-injection defenses.
- Lesson Notes: create from a thread, update from further chat, edit, delete, start a new thread from a note; note ↔ thread links.
- Token usage: total and per thread.
- Admin: upload documents to `s3://…/subjects/<subject>/`; automatic ingestion (extract → chunk → embed → index).
- LangSmith tracing + evaluation suites (§10) gating releases.
- Agent deployed on Bedrock AgentCore.

### v1.1
- Per-user monthly token quotas with warnings and hard limits.
- Web search (Tavily, later self-hosted Firecrawl) as an **explicit, labeled** fallback restricted to the thread's subject.
- Admin UI for subjects, documents, ingestion status.
- Conversation search / history filters.

### Later
- Note sharing, cross-subject threads, multilingual UI, mobile app, learner analytics for admins.

## 8. User stories and acceptance criteria (MVP)

**US-1 Register and sign in**
- *Given* a new visitor, *when* they register with email + password, *then* a Keycloak account with the `learner` role is created and they land on subject selection.
- Unauthenticated calls to the API, agent, or MCP server return `401`.

**US-2 Choose subjects**
- *Given* a signed-in learner, *when* they open subject selection, *then* they see every subject that exists in S3/DB and can enroll in or leave any of them.
- Leaving a subject hides its threads from "new chat" but does not delete existing threads or notes.

**US-3 Ask a grounded question**
- *Given* a thread for subject *S*, *when* the learner asks an in-scope question, *then* the streamed answer is based on chunks retrieved **only from S** and lists ≥1 citation (document title, page/section).
- If no retrieved chunk supports an answer, the agent states that the material does not cover it.

**US-4 Off-topic rejection**
- *Given* a thread for subject *S*, *when* the learner asks something unrelated to *S*, *then* the agent declines briefly and suggests in-scope topics; no retrieval for another subject occurs.

**US-5 Prompt-injection resistance**
- *When* user input or retrieved text contains instructions (e.g. "ignore previous instructions", "search subject X"), *then* the agent does not change its scope, reveal its system prompt, or access other subjects or users' data.

**US-6 Create / update a Lesson Note**
- *When* the learner asks the agent to "summarize this lesson", *then* a Markdown note is written to S3 under the learner's prefix, linked to the thread, and shown in their notes list.
- *When* they later ask to update it from the same or a linked thread, *then* the note is rewritten and the new thread is added to its links.

**US-7 Manage Lesson Notes**
- The learner can view, edit (Markdown editor), and delete their notes; deleting a note does not delete threads.
- *When* they choose "Discuss this note", *then* a new thread for the note's subject starts with the note as context and is linked to it.

**US-8 Token usage**
- The learner sees total tokens (input/output) and tokens per thread; figures match LangSmith/agent records within one completed turn.

**US-9 Admin ingestion**
- *When* an admin uploads, replaces, or deletes a document under `subjects/<subject>/`, *then* within 5 minutes its chunks are added, re-indexed, or removed in pgvector with metadata: `subject`, `document_id`, `title`, `source_uri`, `page`, `section`, `checksum`, `ingested_at`.
- Re-processing the same file is idempotent (no duplicate chunks).

**US-10 Data isolation**
- A learner can never read, list, or modify another learner's threads, notes, or usage — verified by automated tests against the API and S3 paths.

## 9. Solution overview

```
 Web App (React) ──► API Server (FastAPI) ──► Smart Tutor Agent (LangChain Deep Agents on Bedrock AgentCore)
       │                    │                         │            │
       └── Keycloak (OIDC) ◄┴──── token validation ───┘            ▼
                                                          RAG MCP Server ──► PostgreSQL + pgvector
 Admin ──► S3 subjects/ ──► S3 event → SQS → Ingestion worker (Docling → chunk → embed) ──┘
```

| Component | Responsibilities |
|---|---|
| **RAG MCP Server** | `search(query, subject, k)` tool; validates the caller's token and rejects subjects the user is not enrolled in; returns chunks + citation metadata. |
| **Ingestion worker** | Consumes S3 events; extracts with Docling; chunks; embeds; upserts/deletes by `document_id` + `checksum`. |
| **Smart Tutor agent** | Scope check, retrieval via MCP, cited answer, Lesson Note tool (writes to `s3://…/users/<user_id>/notes/`). Checkpointer and long-term memory in PostgreSQL. |
| **API Server** | Auth, threads, streaming (SSE), notes CRUD, usage stats; propagates user identity to the agent. |
| **Web App** | Login/registration, subject selection, chat, notes editor, usage view. |

### Stack
| Concern | Choice |
|---|---|
| Agent framework | LangChain (Deep Agents / LangGraph) |
| Tracing and evaluation | LangSmith |
| Document extraction | Docling |
| LLM | `gpt-5.4-nano` on AWS SageMaker *(confirm availability — §13)* |
| Embeddings | `text-embedding-small` on AWS SageMaker *(confirm)* |
| Vector store / app DB | PostgreSQL + pgvector |
| Identity | Keycloak (OIDC; roles `learner`, `admin`) |
| Storage | S3 (documents, Lesson Notes) |
| Agent hosting | AWS Bedrock AgentCore |
| API / Web | FastAPI / React |

## 10. Quality, safety, and evaluation

All suites run in LangSmith on every change to prompts, tools, or retrieval; MVP releases are gated on the targets below.

| Suite | Dataset (initial) | Metric | MVP target |
|---|---|---|---|
| Retrieval | 50 Q→expected-chunk pairs per subject | Recall@5 | ≥ 0.85 |
| Groundedness | Same questions, judged answers | Claims supported by cited chunks | ≥ 90% |
| Citation accuracy | Same | Citation points to a supporting chunk | ≥ 95% |
| Scope guard | 100 in-scope + 100 off-topic questions | Off-topic rejected (recall) / in-scope wrongly rejected (false-reject rate) | ≥ 95% / ≤ 5% |
| Prompt injection | 50 direct + indirect (in-document) attacks | Attacks that change scope, leak prompt, or cross users | 0 |
| Trajectory | 30 scripted multi-turn tasks | Expected tool sequence followed (e.g. search before answering; note tool on request) | ≥ 90% |

**Online monitoring:** trace every run; sample production traces for groundedness and scope; alert on error rate, latency, and token spikes.

**Defenses:** server-side subject filtering (D4), system-prompt scope guard, retrieved text treated as data rather than instructions, tool allow-list, output check for system-prompt leakage.

## 11. Non-functional requirements (pilot scale)

| Area | Target |
|---|---|
| Scale | 50 concurrent learners, ≤ 5 subjects, ≤ 2,000 pages per subject |
| Latency | First streamed token p95 ≤ 3 s; ingestion ≤ 5 min per document |
| Availability | Best-effort; no data loss on restart (checkpointer in PostgreSQL) |
| Security | Every service validates Keycloak JWTs; S3 per-user prefixes; secrets in AWS Secrets Manager; TLS everywhere |
| Privacy | Learner data deletable on request; traces must not contain credentials |
| Cost | Track cost per conversation from day one; set a budget after the first pilot week |
| Language | English UI; content in subject's language |

## 12. Success metrics

- **Quality:** all §10 targets met on release and held for 4 weeks in sampled production traces.
- **Engagement (pilot):** ≥ 60% of registered learners start ≥ 3 threads; ≥ 1 Lesson Note per active learner per week.
- **Trust:** < 5% of answers thumbs-down for "wrong / unsupported".

## 13. Open questions

| # | Question | Blocks | Default if unanswered |
|---|---|---|---|
| Q1 | Are `gpt-5.4-nano` and `text-embedding-small` actually deployable on SageMaker in our region? Alternative: Bedrock-hosted models. | Build | Spike in week 1; fall back to Bedrock models. |
| Q2 | Which subjects and which two books seed the MVP, and do we have rights to index them? | Ingestion, evals | IELTS + AI Agents, one book each. |
| Q3 | Does the API server / MCP server also run on AgentCore (Gateway/Runtime) or on ECS/Lambda? | Deploy | Agent on AgentCore Runtime; MCP via AgentCore Gateway; API on ECS Fargate. |
| Q4 | How does user identity flow API → agent → MCP (token exchange vs. forwarded JWT)? | Auth design | Forward the user's access token; MCP validates audience and enrolled subjects. |
| Q5 | Token quota policy for v1.1 (limit per month? per subject? admin override?) | v1.1 | Tracking only until decided. |
| Q6 | Retention period for threads and traces? | Privacy | 180 days. |
| Q7 | Should off-topic replies be strict or conversational? | UX copy | Short, friendly, suggests in-scope topics. |

## 14. Milestones

| Milestone | Exit criteria |
|---|---|
| M0 Foundations | Repo, CI, Keycloak, PostgreSQL+pgvector, LangSmith project; Q1 spike done |
| M1 RAG MCP | Ingestion pipeline + authenticated MCP search; retrieval eval passing |
| M2 Agent | Grounded Q&A, scope guard, Lesson Note tool; groundedness, scope, injection, trajectory evals passing |
| M3 API + Web | Auth, chat streaming, notes, usage view; isolation tests passing |
| M4 Deploy + Monitor | AgentCore deployment, online evaluation, dashboards and alerts |
