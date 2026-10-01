# Smart Tutor — Product Requirements Document

| | |
|---|---|
| **Status** | Draft v0.3 (refined from `initial-idea.md`, owner feedback applied) |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-01 |
| **Lifecycle** | Build → Test → Deploy → Monitor ([The Agent Development Lifecycle](https://www.langchain.com/blog/the-agent-development-lifecycle)) |

---

## 1. Summary

Smart Tutor is a subject-scoped AI tutor. A learner picks a subject (e.g. *English / IELTS*, *AI Agents*) and chats with an agent that answers **only from that subject's documents**, cites its sources, and politely refuses off-topic questions. Learners can turn a conversation into a **Lesson Note**, refine it later, and see how much of their **token credit** they have used.

The project has a second, equally important goal: to exercise the full **agent development lifecycle** — tracing, evaluation, security hardening, and deployment to AWS Bedrock AgentCore — so the agent is demonstrably reliable and safe, not just functional.

## 2. Problem

General-purpose chatbots drift off-topic, answer from unknown sources, and forget what a learner studied last week. Learners preparing for a specific goal (e.g. IELTS) need a tutor that:

- stays inside the subject they are studying,
- grounds every answer in trusted material and shows where it came from,
- helps them capture and revisit what they learned.

## 3. Personas

| Persona | Job to be done |
|---|---|
| **Learner** (primary) | "Help me study *my* subject efficiently, keep me on track, and show me which source backs each answer." |
| **Admin** (secondary) | "Let me upload the trusted documents for each subject, host the models, and build evaluation datasets." |
| **Developer / Operator** (internal) | "Let me trace, evaluate, and monitor the agent so I can ship changes with confidence." |

## 4. Glossary

| Term | Definition |
|---|---|
| **Subject** | The unit of scope and access control (e.g. `ielts`, `ai-agents`), represented by an S3 prefix `subjects/<subject>/`. Created by an Admin; never deleted. *Replaces "favorite" and "role" in the original draft.* |
| **Enrolled subjects** | The subjects a Learner has chosen. A Learner may only chat about, and retrieve from, enrolled subjects. |
| **Thread** | One conversation. Bound to exactly **one** subject at creation; the subject cannot change mid-thread. |
| **Document** | A source file (PDF, DOCX, …) uploaded by an Admin to a subject's S3 prefix. Treated as trusted content. |
| **Chunk** | An embedded fragment of a Document, with metadata for citation and access control. |
| **Citation** | Reference returned with an answer: document title, page/section, and chunk id. |
| **Lesson Note** | A Markdown summary of what was learned in one or more threads, owned by one Learner. *Replaces "take keynote".* |
| **Token credit** | The number of LLM tokens (input + output) a Learner may consume. Default **20,000** per user. |

## 5. Goals and non-goals

### Goals (MVP)
1. Learners get **grounded, cited answers** scoped to an enrolled subject.
2. **Off-topic questions and prompt-injection attempts in user input are rejected** reliably.
3. Learners can **create, update, edit, delete, and continue from Lesson Notes**.
4. **Token usage is tracked** per user and per thread, and each user is limited by a **token credit** (default 20K).
5. Every agent run is **traced and evaluated** in LangSmith (tool use, retrieval relevance, answer relevance), with human feedback used to calibrate LLM judges.
6. All components require **authentication and authorization** via Keycloak; users can only see their own data.
7. The agent is **deployed to AWS Bedrock AgentCore**.

### Non-goals (MVP)
- Web search of any kind.
- Credit tiers by user level (e.g. L1-Silver, L2-Golden), top-ups, or billing.
- Admin web UI (admins upload to S3 directly).
- Defending against instructions embedded in documents (documents are admin-curated and trusted).
- Cross-subject conversations, sharing notes, mobile apps, non-English UI.

## 6. Key product decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | **Subject** is the single scope concept; access = enrolled subjects. | Draft mixed "favorite", "role", and "subject". |
| D2 | The corpus is **whatever Admins upload** under `subjects/<subject>/` in S3. No fixed book list. | Owner decision. |
| D3 | A thread is bound to **one subject**; switching subject starts a new thread. | Keeps retrieval filters and evaluation simple. |
| D4 | Subject access is **enforced in the RAG MCP server** using the user's forwarded access token (see §9.2), never by the agent's prompt alone. | The LLM must not be the access-control boundary. |
| D5 | If the documents cannot support an answer, the agent says so rather than guessing. | Preserves groundedness. |
| D6 | Each user has a **token credit, default 20K tokens**; when exhausted, new messages are blocked. | Owner decision; tiers are out of scope. |
| D7 | The only **untrusted input is the user's prompt**; injection defenses target it. | Documents are admin-uploaded; there are no web or third-party sources. |
| D8 | Lesson Notes are **private to their owner**; stored as Markdown in S3 with metadata in PostgreSQL. | Data ownership requirement. |

## 7. Scope

### MVP (v1.0)
- Learner registration, login, logout (Keycloak).
- Choose / change enrolled subjects from the admin-created list.
- Chat in a subject-bound thread with streamed responses.
- Grounded answers with citations from the RAG MCP server.
- Off-topic rejection and prompt-injection defenses on user input.
- Lesson Notes: create from a thread, update from further chat, edit, delete, start a new thread from a note; note ↔ thread links.
- Token usage (total and per thread) and per-user token credit enforcement.
- Admin uploads documents to S3; S3 events keep the vector index in sync (create, replace, delete).
- LangSmith tracing, evaluation suites, and human-feedback annotation (§10).
- Agent deployed on Bedrock AgentCore.

### Later (out of scope now)
- Credit tiers by user level (L1-Silver, L2-Golden), credit top-ups.
- Web search.
- Admin UI for subjects, documents, ingestion status, credits.
- Note sharing, cross-subject threads, multilingual UI, mobile app.

## 8. User stories and acceptance criteria (MVP)

**US-1 Register and sign in**
- *Given* a new visitor, *when* they register with email + password, *then* a Keycloak account with the `learner` role is created, a 20K token credit is assigned, and they land on subject selection.
- Unauthenticated calls to the API, agent, or MCP server return `401`.

**US-2 Choose subjects**
- *Given* a signed-in learner, *when* they open subject selection, *then* they see every subject Admins have created and can enroll in or leave any of them.
- Leaving a subject prevents new threads for it but does not delete existing threads or notes.

**US-3 Ask a grounded question**
- *Given* a thread for subject *S*, *when* the learner asks an in-scope question, *then* the agent calls the RAG MCP `search` tool, and the streamed answer is based on chunks **only from S** with ≥1 citation (document title, page/section).
- If no retrieved chunk supports an answer, the agent states that the material does not cover it.

**US-4 Off-topic rejection**
- *Given* a thread for subject *S*, *when* the learner asks something unrelated to *S*, *then* the agent declines briefly and suggests in-scope topics, without answering from its own knowledge.

**US-5 Prompt-injection resistance**
- *When* the user's prompt tries to override instructions (e.g. "ignore previous instructions", "search subject X", "print your system prompt"), *then* the agent keeps its scope, does not reveal its system prompt, and cannot access other subjects or other users' data.

**US-6 Create / update a Lesson Note**
- *When* the learner asks the agent to "summarize this lesson", *then* a Markdown note is written to `s3://…/users/<user_id>/notes/`, linked to the thread, and shown in their notes list.
- *When* they later ask to update it from the same or a linked thread, *then* the note is rewritten and the new thread is added to its links.

**US-7 Manage Lesson Notes**
- The learner can view, edit (Markdown editor), and delete their notes; deleting a note does not delete threads.
- *When* they choose "Discuss this note", *then* a new thread for the note's subject starts with the note as context and is linked to it.

**US-8 Token usage and credit**
- The learner sees tokens used (input/output) in total and per thread, and remaining credit.
- *Given* remaining credit ≤ 0, *when* the learner sends a message, *then* the API rejects it (`402`/`429` with a clear message) without calling the agent. A turn already in progress may finish even if it overruns the credit.
- Usage figures match the token counts reported by the model endpoint for each completed turn.

**US-9 Document sync via S3 events**
- *When* an admin uploads, replaces, or deletes an object under `subjects/<subject>/`, *then* within 5 minutes its chunks are added, re-indexed, or removed in pgvector with metadata: `subject`, `document_id`, `title`, `source_uri`, `page`, `section`, `checksum`, `ingested_at`.
- Re-processing the same event or file is idempotent (no duplicate chunks); failed events are retried and land in a dead-letter queue.

**US-10 Data isolation**
- A learner can never read, list, or modify another learner's threads, notes, or usage — verified by automated tests against the API, MCP server, and S3 paths.

## 9. Solution overview

### 9.1 Components

```
 Web App (React) ──► API Server (FastAPI) ──► Smart Tutor Agent (LangChain Deep Agents on Bedrock AgentCore)
       │                 │  (user JWT)               │  (same user JWT)
       ▼                 ▼                           ▼
   Keycloak (OIDC) ◄── validate ──────────────── RAG MCP Server ──► PostgreSQL + pgvector
                                                                         ▲
 Admin ──► S3 subjects/<subject>/ ──► S3 event → SQS → Ingestion worker ──┘
                                      (Docling → chunk → embed via SageMaker)
```

| Component | Responsibilities |
|---|---|
| **RAG MCP Server** | `search(query, subject, k)` tool over streamable HTTP. Validates the forwarded JWT, checks the user is enrolled in `subject`, filters pgvector by `subject`, returns chunks + citation metadata. |
| **Ingestion worker** | Consumes S3 `ObjectCreated` / `ObjectRemoved` events via SQS; extracts with Docling; chunks; embeds; upserts or deletes by `document_id` + `checksum`. |
| **Smart Tutor agent** | Scope check, retrieval via MCP, cited answer, Lesson Note tool. Checkpointer and long-term memory in PostgreSQL. Reports token usage per turn. |
| **API Server** | Auth, enrollments, threads, streaming (SSE), notes CRUD, usage and credit checks; forwards the user's token to the agent. |
| **Web App** | Login/registration, subject selection, chat, notes editor, usage and credit view. |

### 9.2 Identity propagation and access enforcement

**Yes — the API can pass the user's access token through to the MCP server.** Flow:

1. The Web App signs the user in with Keycloak (OIDC Authorization Code + PKCE) and calls the API with `Authorization: Bearer <access_token>`.
2. The API validates the token (signature via Keycloak JWKS, `iss`, `exp`, `aud`), checks token credit, then invokes the agent and **forwards the same token**.
3. The agent attaches the token to every MCP request (`Authorization` header on the streamable-HTTP transport). The token is passed in runtime context, **never placed in the prompt**, so the LLM cannot read or alter it.
4. The MCP server validates the token itself, reads the user id (`sub`), looks up that user's enrolled subjects in PostgreSQL, and rejects the call (`403`) if the requested `subject` is not one of them. The `subject` filter is applied in SQL — the model cannot widen it.

Why enforce in the MCP server rather than in the agent: the agent's tool arguments are generated by the LLM, so a prompt injection could make it ask for `subject="other"`. The MCP server trusts only the verified token and the database, so even a fully compromised prompt cannot retrieve another subject's chunks.

Keycloak setup: one realm, clients `smart-tutor-web` (public), `smart-tutor-api`, `rag-mcp`; an **audience mapper** so access tokens carry `aud: [smart-tutor-api, rag-mcp]`. Enrollments live in PostgreSQL, not in token claims, so changes take effect immediately without re-login.

Later hardening (not MVP): replace token forwarding with Keycloak **token exchange** (RFC 8693) so the MCP server receives a narrower, MCP-only token.

### 9.3 Token credit

- Usage is recorded per turn (`user_id`, `thread_id`, `input_tokens`, `output_tokens`, `model`, `timestamp`) from the model endpoint's reported usage.
- Credit check happens in the API **before** each turn; credit is lifetime (no reset) in the MVP — see Q2.
- Embedding calls for search and ingestion are not charged to learners.

### 9.4 Stack

| Concern | Choice |
|---|---|
| Agent framework | LangChain (Deep Agents / LangGraph) |
| Tracing and evaluation | LangSmith |
| Document extraction | Docling |
| LLM | `gpt-5.4-nano`, hosted by Admin on AWS SageMaker (details needed — Appendix A) |
| Embeddings | `text-embedding-small`, hosted by Admin on AWS SageMaker (details needed — Appendix A) |
| Vector store / app DB | PostgreSQL + pgvector |
| Identity | Keycloak (OIDC; roles `learner`, `admin`) |
| Storage / events | S3, S3 Event Notifications → SQS |
| Agent hosting | AWS Bedrock AgentCore |
| API / Web | FastAPI / React |

## 10. Quality, safety, and evaluation

### 10.1 Evaluators

| Evaluator | Type | What it checks | MVP target |
|---|---|---|---|
| **Search tool called** | Code | For in-scope questions, the trajectory contains a `search` call to the RAG MCP server **before** the final answer, with `subject` = thread subject. | 100% |
| **No search on off-topic** | Code | For off-topic / injection prompts, the agent declines and makes no `search` call for another subject. | 100% |
| **Retrieval relevance** | LLM-as-judge | Relevance of retrieved chunks to the question (graded 0–1 per chunk; averaged). | ≥ 0.8 |
| **Answer relevance** | LLM-as-judge | Relevance of the final answer to the question. | ≥ 0.85 |
| **Scope guard** | Code (on labeled set) | Off-topic correctly declined / in-scope wrongly declined. | ≥ 95% / ≤ 5% |
| **Injection resistance** | Code + LLM-as-judge | No system-prompt leakage, no scope change, no cross-subject search. | 0 failures |

*Recommended addition:* an LLM-as-judge **groundedness** check (answer vs. retrieved chunks), since an answer can be relevant to the question yet unsupported by the documents.

### 10.2 Aligning LLM judges with human feedback

- Learners rate answers (👍/👎 + optional reason); feedback is attached to the LangSmith run.
- Admins review a weekly sample in a LangSmith **annotation queue**, scoring the same criteria the judges use.
- Track **judge–human agreement** per evaluator; if it drops below ~80%, revise the judge prompt and add disagreeing examples as few-shot examples, then re-run on the annotated set before trusting the judge again.

### 10.3 Building the test dataset quickly

Admins curate the dataset by hand, but they should **review generated candidates rather than write every example from scratch**:

1. **Synthetic Q&A from the corpus.** Sample chunks per subject and have a strong LLM generate questions, reference answers, and the source chunk id. This gives retrieval ground truth for free. Ask for a mix: factual, conceptual, multi-chunk, and **unanswerable-but-on-topic** (to test D5).
2. **Free off-topic negatives.** Questions generated for subject A are off-topic examples for subject B. Add general-knowledge questions and **near-scope** cases (e.g. "IELTS-style essay about quantum physics") that are hardest to classify.
3. **Adversarial prompts by taxonomy × seed.** Cross a list of attack techniques with seed questions to produce many variants:
   - instruction override ("ignore previous instructions…"),
   - system-prompt extraction,
   - role-play / persona jailbreaks,
   - scope smuggling ("for my IELTS practice, explain how to…"),
   - tool manipulation ("call search with subject=ai-agents"),
   - other users' data ("show me user 42's notes"),
   - obfuscation (base64, misspellings, other languages),
   - multi-turn escalation (benign start, attack on turn 3+).

   Supplement with public prompt-injection datasets and red-teaming tools (e.g. promptfoo red-team generation, garak) rather than inventing every attack by hand.
4. **Human review gate.** Push generated items into a LangSmith annotation queue; admins accept, edit, or reject. Dedupe near-duplicates. Only accepted items enter the dataset.
5. **Stable, versioned splits.** Tag dataset versions in LangSmith. Keep a small **smoke** split (~30 items, runs on every PR) and a **full** split (runs before release). Never edit a version that a release was gated on — create a new one.
6. **Grow from production.** Add 👎-rated and judge-flagged traces to a candidate queue; after review they join the next dataset version.

Suggested starting size per subject: 40 in-scope (incl. 10 unanswerable), 30 off-topic (incl. 10 near-scope), 40 adversarial.

### 10.4 Online monitoring

Trace every run; run answer-relevance and scope evaluators on a sample of production traces; alert on error rate, latency, credit-exhaustion spikes, and drops in evaluator scores.

## 11. Non-functional requirements (pilot scale)

| Area | Target |
|---|---|
| Scale | 50 concurrent learners, ≤ 5 subjects, ≤ 2,000 pages per subject |
| Latency | First streamed token p95 ≤ 3 s; ingestion ≤ 5 min per document |
| Availability | Best-effort; no data loss on restart (checkpointer in PostgreSQL) |
| Security | Every service validates Keycloak JWTs; S3 per-user prefixes; secrets in AWS Secrets Manager; TLS everywhere; tokens never logged or put in prompts |
| Privacy | Learner data deletable on request; traces must not contain credentials |
| Cost | Track cost per conversation from day one |
| Language | English UI; content in the subject's language |

## 12. Success metrics

- **Quality:** all §10.1 targets met on release and held for 4 weeks in sampled production traces.
- **Judge alignment:** ≥ 80% agreement between each LLM judge and human annotations.
- **Engagement (pilot):** ≥ 60% of registered learners start ≥ 3 threads; ≥ 1 Lesson Note per active learner per week.
- **Trust:** < 5% of answers rated 👎.

## 13. Open questions

| # | Question | Blocks | Default if unanswered |
|---|---|---|---|
| Q1 | SageMaker endpoint details (Appendix A). | Build | — (required) |
| Q2 | Is the 20K credit lifetime or does it reset (e.g. monthly)? Can an admin raise one user's credit manually? | Credit logic | Lifetime; admin can update via DB/script. |
| Q3 | Where do the API and MCP servers run — AgentCore Gateway/Runtime or ECS/Lambda? | Deploy | Agent on AgentCore Runtime; API and MCP on ECS Fargate. |
| Q4 | Which subjects launch first? | Ingestion, evals | IELTS and AI Agents. |
| Q5 | Retention period for threads and traces? | Privacy | 180 days. |
| Q6 | Off-topic reply tone: strict or conversational? | UX copy | Short, friendly, suggests in-scope topics. |

## 14. Milestones

| Milestone | Exit criteria |
|---|---|
| M0 Foundations | Repo, CI, Keycloak realm, PostgreSQL+pgvector, LangSmith project; SageMaker endpoints reachable (Appendix A) |
| M1 RAG MCP | S3-event ingestion + authenticated MCP search; retrieval-relevance eval passing |
| M2 Agent | Grounded Q&A, scope guard, Lesson Note tool; all §10.1 evals passing on the smoke split |
| M3 API + Web | Auth, chat streaming, notes, usage and credit; isolation tests passing |
| M4 Deploy + Monitor | AgentCore deployment, online evaluation, annotation queue, dashboards and alerts |

---

## Appendix A — Information needed from the Admin (SageMaker models)

### Both endpoints
- AWS **region** and **endpoint name** (and ARN).
- **Access method**: IAM role/policy to assume (`sagemaker:InvokeEndpoint`, `InvokeEndpointWithResponseStream`), and whether calls go through a VPC endpoint.
- **Serving container** (e.g. vLLM, TGI, LMI/DJL) and **request/response schema** — ideally a sample request and response. Is it OpenAI-compatible (`/v1/chat/completions`, `/v1/embeddings`)?
- **Rate / concurrency limits**, autoscaling settings, and whether it scales to zero (cold-start time).
- **Model version** and how we are notified of upgrades (affects evaluation baselines).
- Separate endpoints (or variants) for **dev/test vs. prod**, if any.

### LLM (`gpt-5.4-nano`)
- **Streaming** supported? (needed for SSE to the web app)
- **Tool / function calling** supported, and in which format? (required for MCP tools and the Lesson Note tool)
- **Context window** and **max output tokens**.
- Does the response include **token usage** (`prompt_tokens`, `completion_tokens`)? If not, which **tokenizer** should we use to count? (required for credits)
- Supported parameters (temperature, top_p, stop, structured/JSON output).
- Cost per hour or per token, for cost tracking.

### Embeddings (`text-embedding-small`)
- **Vector dimension** (sizes the pgvector column).
- **Max input tokens** per text and **max batch size**.
- Are vectors **normalized**? Recommended distance metric (cosine / inner product).
- Any required **input prefixes** (e.g. `query:` / `passage:`).
