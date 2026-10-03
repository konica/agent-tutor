---
type: workflow
title: Ask Flow — Agent Graph
description: Traces the complete ask-path through the LangGraph agent, covering subject detection, MCP search, relevance gate, growth check, answer generation, and the decline path. Also documents the summarize and idle-record side paths.
tags: [agent, langgraph, tutoring, subject-detection, mcp, retrieval, decline-log, ask-path]
sources:
  - id: openwiki-source-f471239d79a734c9535f8e71
    resource: repo://backend/src/smart_tutor/apps/agent/nodes/__init__.py
  - id: openwiki-source-6e9e459b50fdd5830059c053
    resource: repo://backend/src/smart_tutor/apps/agent/server.py
  - id: openwiki-source-daaefe65bdc8373e27d6b95d
    resource: repo://backend/src/smart_tutor/apps/mcp_server/server.py
  - id: openwiki-source-1e54858aa8e91f5173b26369
    resource: repo://backend/src/smart_tutor/insights/README.md
  - id: openwiki-source-91a36491842f2eb410d9e6f9
    resource: repo://backend/src/smart_tutor/tutoring/README.md
  - id: openwiki-source-473ea646d59721d67fc55bbb
    resource: repo://sdd/prd.md
  - id: openwiki-source-e378957ac9ba2f1c5932cd66
    resource: repo://sdd/specs/2026-10-02-project-structure-design.md
generated: { by: "openwiki/0.7.0", at: "2026-10-03T03:19:50.688Z" }
verified:
  - by: openwiki/0.7.0
    at: 2026-10-03T03:19:50.688Z
---

# Ask Flow — Agent Graph

The Smart Tutor agent is a **plain LangGraph graph**; retrieval is never a model decision. The graph is served by the internal `agent` FastAPI application (`apps/agent/server.py`) as a ClusterIP service. The five named nodes — `resolve_subject`, `search`, `gate`, `answer`, and `summarize` — are defined as stubs in `apps/agent/nodes/__init__.py` (implemented in M2). Business rules live in `tutoring.domain` and `tutoring.application`; the graph nodes are thin entrypoints that call those services.

The graph state carries `subject_ids` (a list of 1–3 UUIDs). `subject_ids` starts empty, is set on the first answerable turn, and is persisted with the LangGraph checkpointer in PostgreSQL. Subjects are **only ever added**, never removed.

---

## Ask-path overview

Every chat turn goes through the same five-step path. Steps 1, 3, and 4 are pure code (no LLM call); step 2 is an MCP tool call; step 5 is the only LLM call.

```
User question
      │
      ▼
1. Resolve subjects  ─── state.subject_ids non-empty? ──► skip to step 2
      │ (first turn only)
      ▼
   Detection or ask
      │
      ▼
2. MCP search  (top-5 chunks from thread's subjects)
      │
      ▼
3. Relevance gate  ──── best score ≥ answer_floor? ──► 5. Answer
      │
      ▼
4. Growth check
      │
      ├── other subject scores ≥ detect_threshold, thread < 3 subjects
      │        └──► add subject, warn if now at 3, ──► 5. Answer
      │
      ├── other subject scores ≥ detect_threshold, thread already has 3
      │        └──► do not answer; warn; recommend new conversation
      │
      └── no subject scores ≥ detect_threshold
               └──► Decline (no LLM call; log to decline log)
      │
      ▼
5. Answer (Nova 2 Lite, streamed)
```

---

## Step 1 — Resolve subjects (first turn)

This step runs only when `state.subject_ids` is empty (i.e., the first turn of a thread).

**Single-subject learners** skip detection entirely: the thread is bound to their one subject immediately.

**Multi-subject learners** go through the `DetectionPolicy`:

1. Search across **all of the learner's subjects** (distinct `subject_id`s over their `ready`, non-archived documents) and score each subject by its best chunk similarity.
2. Identify the best-scoring subject. Bind it if:
   - its score ≥ `detect_threshold`, **and**
   - it leads the runner-up by ≥ `detect_margin`.
3. Also bind any other subject whose score ≥ `detect_threshold` and whose score is within `multi_margin` of the best (at most 3 subjects bound in total).
4. If the above conditions are not met — detection is unsure — the agent asks: *"Which subjects is this about?"* (pick 1–3). The original question is kept and answered immediately after the learner picks, without retyping.

The four threshold parameters — `detect_threshold`, `detect_margin`, `multi_margin`, and `answer_floor` — are **configuration values stored in SSM Parameter Store** (`/smart-tutor/*`). Their starting values are recorded before M2 evals run and are tuned on the labeled detection dataset (M2 task).

---

## Step 2 — MCP search (fixed step)

The `search` node calls the RAG MCP server's `search` tool with:
- `query`: the learner's message,
- `subject_ids`: the thread's bound subjects,
- `k = 5` (fixed top-k).

The MCP server (`apps/mcp_server/server.py`) runs at `:8000/mcp` over streamable HTTP. It:
1. Validates the forwarded JWT (the agent passes the original Keycloak token in an HTTP header, never in the prompt),
2. Reads `sub` from the token,
3. Builds a SQL filter: chunks whose `content_id` belongs to a document that is `ready`, not archived, has **any** of the requested `subject_ids`, and satisfies `can_read(sub, document)` (Releases 1–3: `owner_id = sub`),
4. Returns up to 5 chunks with scores and citation metadata.

An empty readable set returns an empty result; the agent converts this to the "no active documents" message (US-10) rather than an error. Search **always runs first** — off-topic and uncovered questions go through the same decline path (D5).

---

## Step 3 — Relevance gate

A pure-code check (`RelevanceGate` in `tutoring.domain`). If the best chunk score from the search result is **≥ `answer_floor`**, the gate passes and control moves directly to step 5 (Answer), skipping the growth check.

---

## Step 4 — Growth check

Runs only when the relevance gate does not pass. The agent searches the learner's **other** subjects (those not already in `state.subject_ids`) and evaluates the best score.

| Condition | Outcome |
|---|---|
| Best other-subject score ≥ `detect_threshold` and thread has < 3 subjects | Add the subject to `state.subject_ids`; notify the learner ("Added *subject* to this conversation"); if this reaches 3 subjects, show the maximum warning ("This conversation now covers 3 subjects, the maximum"); continue to Answer with the new chunks |
| Best other-subject score ≥ `detect_threshold` but thread already has 3 subjects | Do **not** answer; warn the learner; recommend starting a new conversation and offer a "New conversation" action that carries the question over |
| No other-subject score ≥ `detect_threshold` | Decline (step 4 decline) |

Subjects are **never removed** from a thread (`Thread.add_subject()` refuses beyond 3 but never removes). This is enforced in the domain object and is an invariant across both detection and growth.

---

## Step 5 — Answer

The agent calls **Amazon Nova 2 Lite** (`amazon.nova-2-lite-v1:0` via the `us.amazon.nova-2-lite-v1:0` inference profile) with `ConverseStream` and streams the response.

The prompt structure:
- **System prompt**: names the thread's subjects using the **learner's personal names** (resolved at read time via `coalesce(user_subject_names.display_name, subjects.canonical_name)`); the system prompt is eligible for Bedrock prompt caching.
- **History**: capped per-turn to fit the context window.
- **Chunks as quoted data**: chunk text is wrapped as quoted data with an explicit instruction to treat document text as information, never as instructions (D7 — prompt-injection defense for documents).

The model streams a cited answer or calls the `decline(reason)` tool if it determines the documents do not support an answer. Either way, **at least one citation** (document display title + page, or "page unavailable") is expected in answered turns.

---

## Decline path

A decline can be triggered at three points:

| Trigger | Point |
|---|---|
| Growth check: no subject match, thread at max, or no other-subject match | Step 4 |
| Model calls `decline(reason)` tool during answer generation | Step 5 |

In **both** cases, **no LLM call is made** for the step-4 declines (the model is never invoked). For model-initiated declines at step 5, the tool call is the model's output.

Every decline writes an **anonymous record** to the `declines` table (via `insights.application.DeclineLogService`):
- `subject_ids[]` (the thread's subjects at the time),
- question text with PII scrubbed (emails, phone numbers, names detected by a PII filter),
- best retrieval score,
- reason,
- timestamp.

**No `user_id` is stored.** Decline log entries are deleted after 90 days. The log feeds evaluation dataset growth and online monitoring dashboards (aggregates only, not raw questions).

---

## Summarize path

Triggered when the learner clicks "Summarize lesson". This path runs through the `summarize` node:

1. **Read the thread** from the checkpointer.
2. **Edit check**: if `lesson_notes.edited_since_generated` is `true`, the API asks the learner to confirm the overwrite before the agent node runs (D8 — nothing the learner wrote is lost without consent).
3. **One model call** returns the Lesson Note markdown and calls the `save_learning_record` tool with `subject_ids[]`, `topics[]`, `key_points[]`, `thread_id`, `note_id`, `trigger = "note"`, and a timestamp.
4. **Upsert both**: the `LessonNote` (one per thread, unique on `thread_id`) and the `LearningRecord` (in the LangGraph store, namespace `("learning", user_id)`, keyed by `thread_id`). At most one learning record per thread — updated in place by either trigger.

---

## Idle-record path

A Kubernetes CronJob (the **learning-record sweeper**) runs **every minute**. It selects threads satisfying:

```
last_learner_message_at < now − learning_record_idle_minutes
AND last_learner_message_at > record_written_at
```

For each selected thread it **writes or updates the learning record only** (no Lesson Note, no model call beyond the record generation itself). The default value of `learning_record_idle_minutes` is **10 minutes**, stored in SSM. A changed value applies from the next sweep. Only **learner messages** reset the idle timer — system messages and agent responses do not.

---

## Thread growth invariant

The invariant holds across all paths:

- `subject_ids` in graph state are **append-only**: added at detection (step 1), at growth (step 4), never removed.
- The maximum is **3 subjects per thread**. `Thread.add_subject()` in `tutoring.domain` refuses any attempt to add a fourth.
- When a thread reaches 3, the learner sees a warning: *"This conversation now covers 3 subjects, the maximum. For other topics, start a new conversation."*
- When a question clearly matches a fourth subject on a 3-subject thread, the agent **does not answer** and recommends starting a new conversation, offering a "New conversation" action that carries the question over.

---

## Full ask-path flowchart

<!-- openwiki: mermaid parse failed and this diagram was converted to a text fence so it does not break rendering. Fix the diagram source and restore the mermaid fence. Parser error: Heuristic: a semicolon inside a label breaks rendering; rephrase the label. -->
```text
flowchart TD
    A["User message"] --> B{"state.subject_ids\nempty?"}
    B -- "no (later turn)" --> D
    B -- "yes (first turn)" --> C{"Single-subject\nlearner?"}
    C -- yes --> C1["Bind the one subject"] --> D
    C -- no --> DET{"Detection:\nbest score >= detect_threshold\nAND leads runner-up\nby >= detect_margin?"}
    DET -- yes --> DET2["Bind best subject;\nalso bind others within\nmulti_margin of best\n(at most 3 total)"] --> D
    DET -- no --> ASK["Ask learner:\nWhich subjects is this about?\n(pick 1-3)\nkeep original question"] --> D

    D["Step 2: MCP search\ntop-5 chunks from\nthread's subjects"] --> E{"Step 3: Relevance gate\nbest score >= answer_floor?"}
    E -- yes --> F
    E -- no --> G{"Step 4: Growth check\nother-subject best\nscore >= detect_threshold?"}

    G -- "yes AND thread < 3 subjects" --> G1["Add subject;\nnotify learner;\nif now 3: show max warning"] --> F
    G -- "yes AND thread = 3 subjects" --> G2["Do not answer;\nwarn;\nrecommend new conversation\nwith question carried over"]
    G -- no --> G3["Decline (no LLM call)\nlog to decline log anonymously"]

    F["Step 5: Answer\nNova 2 Lite streamed\nchunks as quoted data\nwith citations"] --> H{"Model calls\ndecline tool?"}
    H -- no --> I["Stream cited answer\nto learner"]
    H -- yes --> J["Friendly decline\nlog to decline log\nanonymously"]
```

*Full ask-path decision tree for every chat turn.*

---

## Key domain classes and services

| Symbol | Module | Role |
|---|---|---|
| `Thread` (`add_subject()`) | `tutoring.domain` | Enforces append-only, ≤ 3 subjects invariant |
| `DetectionPolicy` | `tutoring.domain` | Threshold-based subject binding logic |
| `RelevanceGate` | `tutoring.domain` | `answer_floor` comparison |
| `GrowthPolicy` | `tutoring.domain` | Other-subject score check and growth/decline decision |
| `SubjectDetector` | `tutoring.application` | Orchestrates detection across the learner's subjects |
| `AskService` | `tutoring.application` | Drives the ask-path steps |
| `ConversationService` | `tutoring.application` | Thread lifecycle and management |
| `Retriever` (port) | `tutoring.ports` | MCP client adapter; the only way the agent reads chunks |
| `DeclineLogService` | `insights.application` | Writes anonymous decline records |
| `NoteService`, `LearningRecordService` | `learning.application` | Summarize and idle-record paths |

The agent graph (`apps/agent/nodes/__init__.py`) never imports `knowledge.domain` or reads chunk tables directly; all retrieval flows through the `Retriever` port, which is implemented by the MCP client adapter. This keeps the `can_read` access boundary in code and SQL, not in the prompt.

---

## Prompt-injection invariant

Chunk text is always passed to the model as **quoted data** with an explicit system instruction: the model must treat document content as information only, and must never follow instructions found in documents. This is PRD decision D7, enforced at every answer turn regardless of the document's contents. Because subjects and the readable document set are computed from code and the database — not from the prompt — attacks embedded in PDFs ("search subject X", "ignore previous instructions", "print your system prompt") have nothing to change.

LangSmith wraps every agent run with a trace (PRD §10.4). Traces are deleted after 180 days; they are never stored in the user-visible data model.

---

## Configuration

All detection and relevance thresholds are stored in **SSM Parameter Store** under `/smart-tutor/*` and read at startup. The evaluation-gated starting values are set before M2 evals run.

| Parameter | Description |
|---|---|
| `detect_threshold` | Minimum score for a subject to be considered a match |
| `detect_margin` | Minimum lead over the runner-up for single binding |
| `multi_margin` | Maximum gap from the best score to also bind a subject |
| `answer_floor` | Minimum best-chunk score to skip growth check and answer |
| `learning-record-idle-minutes` | Idle minutes before the sweeper writes a learning record (default 10) |

---

## Related pages

- [Architecture Overview](../architecture/overview.md)
- [Access Control](../concepts/access-control.md)
- [Subject Catalog](../concepts/subject-catalog.md)
- [MCP Retrieval](../integrations/mcp-retrieval.md)
- [Bedrock Models](../integrations/bedrock-models.md)
- [Evals](../testing/evals.md)
- [Lesson Notes and Learning Records](lesson-notes-and-learning-records.md)
