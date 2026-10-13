# 0019. Follow-ups search with a model-written standalone query

- Status: proposed (accepted when the implementing PR merges)
- Date: 2026-10-13

## Context

PRD v2.47 (#210) made a follow-up search with the previous question added before the current one, in code with no model call. Review found two weak spots: a topic named more than one turn back is lost ("Why does model size matter for it?" after two follow-ups about chain-of-thought), and a question on a new topic is searched with the old topic in front of it, which pulls the embedding and the relevance gate toward the old document.

Search is one dense query (pgvector cosine, k = 5) and the gate compares the best cosine score with `answer_floor`, so any fix must keep scores that are cosine scores.

## Decision

- **A `rewrite` step before search.** For a question with history, a `rewriter` model role (Nova 2 Lite, temperature 0, 80 output tokens) turns the question into one standalone search query. It reads the capped history's questions, the last answer cut to 600 characters, and the question, all as escaped, tagged data. It is told to return the question unchanged when it stands alone or changes topic. A first question makes no model call.
- **Search the rewrite and the raw question, merged by cosine score.** Both are searched in parallel; chunks are merged by id with their highest score, and the top 5 go to the answer and the gate. The gate itself doesn't change.
- **Fall back to the code-built query.** A timeout (2.5 s), an error, or an empty rewrite searches with today's previous-plus-current query, so a model outage changes nothing.
- **The rewrite is only a search string.** The answer model still reads the original question; the learner never sees the rewrite.

## Why

- Prompted LLM rewriting is the strongest simple method in the conversational-search literature (TREC CAsT, TopiOCQA), and one call handles both pronoun chains and topic switches, which no code rule tells apart: a pronoun follow-up and a topic switch both look unlike the previous question.
- The raw-question search is a cheap safety net for a rewrite that keeps the old topic or drops a detail; merging by cosine score keeps `answer_floor` meaningful.
- **Rejected:** joining more earlier questions (fixes one-turn lookback, worsens topic switches); an embedding-similarity topic-shift detector (can't tell a pronoun follow-up from a switch); RAG-Fusion with reciprocal rank fusion (more calls, no cosine score for the gate, no end-to-end gain in a 2026 study); HyDE (a made-up passage raises scores for uncovered questions and hides correct declines); boosting the conversation's documents used (pushes topic switches back to the old document); a trained rewriter or conversational retriever (training data and hosting for little gain at pilot scale).

## Consequences

- Follow-ups cost one more model call: about $0.0003 and 0.4–0.8 s before the answer starts. First questions are unchanged.
- The rewriter reads untrusted text. Its output can only change what the learner's own search finds; access stays with `can_read` in SQL. An injection eval row covers it.
- `answer_floor` must be tuned (US-5) on the merged scores.
- A new code evaluator, `follow_up_source_hit_at_5` (≥ 0.95), measures follow-up retrieval directly instead of inside the averaged `retrieval_relevance`.
- If the raw-question search brings in off-topic chunks for vague follow-ups, it can be dropped without changing the rest.
- Spec: `sdd/specs/2026-10-13-follow-up-query-rewrite-design.md`.
