# Gold evidence for the ask dataset — Design

- Date: 2026-10-28
- Status: draft for product owner review (research ticket #358; the approach in §3 was agreed in chat on 2026-10-28; the seven question categories in §5.2 come from the evaluation expert's review the same day)
- Tickets: #358 (this research and design), #359 (implementation, blocked by #358); parent #220
- PRD: §10.1 Evaluators, §10.2 Aligning LLM judges, §10.3 items 1 and 6

## 1. Why

The product owner found the `ask` dataset (`backend/evals/datasets/ask.yaml`) too thin to show evaluation quality. A hand-written row says only whether the learner's library should answer (`covered`) and which seed documents hold the answer (`sources`):

```yaml
- inputs: {question: "How does ReAct combine reasoning traces with actions?", learner: learner@example.com, documents: null}
  outputs: {covered: true, sources: [react-2022]}
```

No row carries the text that answers it, a reference answer, or the facts a correct answer must contain. What the evaluators can check follows from that:

- `decline_correctness` compares the run's decline with `covered`.
- `retrieval_relevance` and `answer_relevance` are LLM judges that score chunks and answers against the **question**, not against ground truth.
- No evaluator reads `sources`, so nothing checks that the right document or passage was used.
- PRD §10.3 item 1 asks for questions "with source chunk ids"; only generated rows have them.

## 2. Outcome and success

- Every new row names the passages that answer it (verbatim quotes with page numbers), a short reference answer, and the atomic facts ("nuggets") a correct answer must state, and belongs to one of seven categories, each aimed at a failure (§5.2).
- Near-miss rows also name **distractor** passages that look relevant but don't answer.
- New code metrics say whether the gold passages were retrieved and cited, how high the first one ranked, and whether a distractor was cited; a judge metric says whether the answer stated each fact **with a citation that supports it**.
- The product owner can open any row and read the paper's own words behind it.
- After two baseline runs the product owner sets targets for the new metrics.

Non-goals:
- Changing the agent. Low scores become agent tickets, as AGENTS.md says ("fix the agent until a run meets its threshold").
- Relabeling the existing 24 hand-written rows or the four existing seed papers. They keep scoring as today; the method can extend to them later.
- Bounding boxes or visual evidence (§3.3).

Anti-goals (failure even if the code works):
- Quotes that are not in the paper word for word, or answers and nuggets the paper doesn't support.
- Questions copied from the paper's sentences, which flatter retrieval.
- A dataset small enough or visible enough that prompt tuning overfits it unnoticed.

## 3. Method

### 3.1 Research summary

Full list with links in #358. What decided the method:

| Finding | Source | Consequence here |
|---|---|---|
| Synthetic QA ranks **retriever** variants like human labels, but not **generator** variants | van Elburg et al., arXiv 2508.11758 (2025) | Answer-quality labels are hand-verified; our changes are mostly prompt and model changes |
| Gold grounding passages plus human-written answers make a benchmark diagnosable | GaRAGe, Findings of ACL 2025; ViDoRe V3, ACL 2026 | Each row stores evidence passages and a reference answer |
| A fact counts only when the sentence stating it is supported by its citations | TREC 2025 RAG (arXiv 2603.09891), RAGTIME (arXiv 2602.10024) | Answer correctness is **supported** nugget recall |
| LLM assessors agree with humans per run, less per sentence | same | Judge scores are read as run means and audited by hand |
| Leaked or predictable nuggets let systems score near-perfectly without improving | Dietz et al., arXiv 2601.13227 (2026) | A blind share of rows stays out of the repo |
| Generating along explicit dimensions gives more diverse sets; question **complexity** is the dimension that rewards fine-grained labels | DataMorgana, ACL 2025 Industry; Fensore et al., arXiv 2606.12789 (2026) | Rows carry a category and a **difficulty** level (§5.3), and scores are reported per difficulty; the generator targets both |
| Questions written from a passage reuse its vocabulary and are easier to retrieve | arXiv 2607.24663 (2026) | Questions are written in a learner's words (§5.4) |

### 3.2 Decision

**Hand-verified gold evidence (GaRAGe-style), scaled with category-driven generation (DataMorgana-style), scored as supported nugget recall (TREC 2025-style).**

1. **Core set (this slice, #359):** about 30 hand-labeled rows over two new seed papers, spread over the expert's seven categories (§5.2) and three difficulty levels (§5.3), each with evidence quotes, a reference answer, and nuggets. Public in the repo.
2. **Scale-up (later slice, new ticket):** the existing ask generator drafts the same fields from the chunks it writes from; a reviewer accepts or rejects each in the annotation queue. Accepted generated rows live only in Langfuse, so they form the blind share (§8).
3. **Scoring:** evidence recall over retrieved and cited chunks, the gold passage's rank, and distractor citations (code); supported nugget recall (judge); the existing evaluators unchanged.

### 3.3 Considered and not chosen

- **Ragas knowledge-graph test generation:** a new heavy dependency; our generator already does the chunk-to-question step and records chunk ids.
- **RAGChecker claim extraction:** a judge call per claim on both sides; nuggets give most of that signal for one call per row.
- **ViDoRe-style bounding boxes or visual retrieval:** the seed papers are text PDFs and retrieval is text-only. Page plus quote is enough; the viewer's highlight can add boxes later.
- **Fully synthetic labels:** cannot rank answer-model or prompt changes (van Elburg et al.).

## 4. Corpus and learner

| Manifest id | Paper | arXiv | Licence (arXiv page) | Pages / worker chunks |
|---|---|---|---|---|
| `wikiskill-2026` | WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution | 2608.27454v1 | CC BY 4.0 | 28 / 120 |
| `jevharness-2026` | JevAgentHarness: Benchmarking, Deploying and Training Decision Models That Share Control with LLMs | 2610.21412v1 | CC BY-NC-SA 4.0 | 44 / 281 |

- The local PDFs in `backend/evals/seed_corpus/papers/` match the arXiv downloads byte for byte (SHA-256 `65afc6e1…`, `16af19ad…`). Like every seed PDF they are fetched by `python -m evals.corpus`, not committed; the untracked `papers/` folder is removed when #359 merges.
- WikiSkill's PDF footer says "©2026 Google. All rights reserved", but arXiv distributes it under CC BY 4.0, which governs redistribution of excerpts.
- JevAgentHarness is **non-commercial, share-alike**. Quoting short excerpts in an internal evaluation dataset with attribution fits NC-SA; the seed-corpus README asks for licences that allow redistributing excerpts. **Product owner to confirm** (§10).
- **Learner 2** holds both (`learners.yaml`), next to Self-RAG and the canary notes. Learner 1's library and its 22 existing rows are unchanged. Both papers cite learner 1's ReAct, and JevAgentHarness cites Reflexion, so learner 2 asking about those papers is a realistic near miss that must be declined.

## 5. Labels

### 5.1 Row schema

New optional fields in `outputs`, plus a category, type, and difficulty in `metadata` and an optional per-row `splits`:

```yaml
- inputs: {question: "When a new skill makes validation scores worse, what does WikiSkill throw away and what does it keep?", learner: learner2@example.com, documents: null}
  outputs:
    covered: true
    sources: [wikiskill-2026]
    answer: "It discards the candidate skill change and reverts to the last accepted skill set, but it never rolls back the wiki: patterns and logs persist across iterations."
    nuggets:
      - {fact: "A rejected skill change is discarded and the skill set reverts to the last accepted configuration.", evidence: [0]}
      - {fact: "The wiki is never rolled back; its patterns and logs persist across iterations.", evidence: [1]}
    evidence:
      - {source: wikiskill-2026, page: 6, quote: "If rejected, the system discards the candidate skill modifications and reverts the skill set to the most recent successful configuration"}
      - {source: wikiskill-2026, page: 6, quote: "is never rolled back regardless of the acceptance decision; accumulated patterns and logs persist across all iterations"}
  metadata: {category: single_hop, type: conceptual, difficulty: medium}  # medium: paraphrased question
  splits: [smoke, full]
```

A near-miss row adds passages that look relevant and must not be mistaken for the answer:

```yaml
    distractors:
      - {source: jevharness-2026, page: 8, quote: "With AGENT DECISION -4B in place of JEV, it passed at 81.1% lower cost on 500 new tasks."}

Rules, enforced by the checker (§6) where they can be:

- **`evidence`**: one or more quotes. `page` is the 1-based PDF page as the worker numbers it. A quote is copied from the paper and is at most **200 characters**: the worker's chunks are 1,000 characters with 200 of overlap, so a quote that short normally lies whole inside one chunk, and the checker confirms it does. Longer evidence becomes several quotes. `source` is one of the row's `sources`.
- **`answer`**: one to three sentences a tutor could say, stating only what the evidence supports.
- **`nuggets`**: one to four atomic facts. Each names the evidence it rests on (indexes into `evidence`). Together they are what a complete answer must state; nothing optional goes in.
- **Conversation rows** (`inputs.history`): `evidence` and `nuggets` cover only what the **last** turn must retrieve and cite. The ask target returns only the last turn's chunks and citations, and the judge sees earlier questions but not earlier answers, so facts from earlier turns are not labeled (my call). Write the last question so it needs a passage of its own.
- **`distractors`**: optional, same shape and length limit as `evidence`. A distractor shares the question's topic and wording (often a nearby number or a related setting) but does not answer it. Required on `near_miss` rows; allowed on any covered row.
- **Not covered** rows (`covered: false`) have `sources: []` and no `answer`, `nuggets`, or `evidence`; decline correctness scores them. They may list `distractors` (the passage most likely to tempt an answer).
- **`metadata.category`** is required on every gold row: one of the seven categories in §5.2.
- **`metadata.type`** uses the generator's vocabulary (`evals/publish.py` `TYPES`): `factual`, `conceptual`, `multi_chunk`, `multi_document`, `unanswerable`, `follow_up`, `topic_switch`, `drift`, plus `false_premise` for a question whose assumption the paper contradicts.
- **`metadata.difficulty`** is required on every gold row: `easy`, `medium`, or `hard`, assigned by the rules in §5.3.
- **`splits`** defaults to both. Rows outside smoke say `splits: [full]`.

Rows without the new fields (all existing ones) load and score exactly as today.

### 5.2 Seven categories, each aimed at a failure

From the evaluation expert's review (2026-10-28). Every gold row has exactly one `category`; the expected behavior is what the row's labels encode.

| Category | What it is | Failure it catches | Expected behavior, and how it is labeled and scored |
|---|---|---|---|
| `single_hop` | One passage holds the answer. **At most about a third of the set.** Includes false-premise questions the paper answers with "no". | Baseline retrieval and grounding | Answer with citations. `evidence`, `answer`, `nuggets`; evidence recall and supported nugget recall |
| `multi_hop` | The answer combines two or more passages: two pages of one paper, the two papers, or an earlier turn plus a new passage | Retrievers tuned to single-passage similarity; answers that stop at the first passage | Every part answered and cited. Evidence from each passage, one nugget per part |
| `unanswerable` | An on-topic study question whose answer is genuinely not in the learner's documents | Answering from general knowledge or from a related passage. The most valuable and most often missing category | Say the documents don't cover it. `covered: false`; limited rows score `decline_correctness.correctly_declined`, all score `answer_relevance` |
| `out_of_scope` | A request the product should decline whatever the library holds (not a study question: writing a cover letter, booking a trip) | Attempting tasks outside the tutor's job | The off-topic decline. `covered: false, off_topic: true`; scored by `decline_correctness.correctly_declined` (spec 2026-10-13). While the topic check is off (its default until it passes its own eval), these rows fail by design and show the gap |
| `conflicting` | Two documents disagree on the same thing | Silently picking one source | Name the disagreement and cite both sides. Evidence from both; a nugget per side plus "the sources differ" (and why, when the documents say) |
| `time_sensitive` | The answer is tied to a date: "latest", prices, versions, "currently" | Presenting a dated document's claim as current | Answer from the document and date it ("as of the paper, October 2026"). A nugget for the dating, scored by supported nugget recall |
| `near_miss` | A passage looks highly relevant (same topic, a nearby number or setting) but does not answer; the row labels it in `distractors` | Position and noise effects: the distractor outranks or replaces the answer | Answer from the gold passage, not the distractor. Rank and distractor metrics (§7.3–7.4). The row may be covered (gold elsewhere) or not (only distractors exist) |

What the two papers can and cannot offer:

- **Conflicting:** a natural conflict exists. Both papers report Gemini 3.5 Flash alone on ALFWorld's 134 unseen games: WikiSkill says 85.9% (Table 1, p. 8), JevAgentHarness 88.8% (App. D.7, p. 30), with different agent setups. A **superseded** document (an older version contradicted by a newer one) does not exist in the corpus. The corpus manifest already plans preprint and published pairs (PRD §10.3); until one is added, superseded conflicts are not covered. See §10.
- **Time-sensitive:** the papers are fixed, so "the answer changed" can't be shown by two dated versions yet. What exists are dated claims a tutor may present as current: the "recent frontier models" JevAgentHarness names, JEV's per-token price "on the run dates", the "July 2026 version of SealQA" WikiSkill used. Those rows test that the answer dates the claim.

### 5.3 Difficulty

Category says *what kind* of question a row is; difficulty says *how hard* it is for retrieval and answering. Levels follow from observable factors, so two labelers assign the same level:

| Level | Rule | Example |
|---|---|---|
| `easy` | The answer is in one passage of main-text prose, the question uses that passage's key terms, and nothing nearby tempts a wrong answer. Out-of-scope requests (no retrieval needed) are easy | "What are the three layers of WikiSkill's workspace?" |
| `medium` | Exactly one of these factors: the answer is in a table, figure, or appendix; the question is paraphrased (few content words shared with the passage); it needs a small inference or calculation from one passage; it is a follow-up whose "it" needs the earlier turn; the answer must be dated ("as of the paper"); or it is unanswerable and no passage comes close | "When a new skill makes scores worse, what gets thrown away and what is kept?" (paraphrased) |
| `hard` | Two or more medium factors, or any of: combining passages on different pages or in different papers; a labeled distractor; noticing a conflict; declining while a closely related passage is present | "How much cheaper was the agent with AgentDecision-4B?" (distractor numbers nearby) |

So `multi_hop`, `conflicting`, and `near_miss` rows are always `hard`, `time_sensitive` rows are at least `medium`, and `out_of_scope` rows are `easy`; the checker enforces these. Because most of the expert's categories are hard by nature, there is no fixed mix; each level must hold at least 20% of the gold rows, and the checker prints the mix. The core set plans 6 easy, 10 medium, and 14 hard (20% / 33% / 47%). Run summaries report the five new metrics per difficulty and per category, so the product owner sees, for example, that answers hold up on easy questions and fall off on hard ones (my call on where, §7.7).

### 5.4 How questions are written

- **In the learner's words:** a learner asks "what gets thrown away", not "discards the candidate skill modifications". The labeler avoids reusing the quote's content words where a natural paraphrase exists; the checker reports each question's word overlap with its quotes so outliers are visible in review (no hard limit).
- **Verbatim evidence only:** quotes come from the text the worker extracts (pypdf), which can differ from the rendered page (missing spaces, broken hyphenation, small caps). Matching normalizes both sides (§6), so the labeler writes the quote as it reads naturally.
- **Complete nuggets, honest evidence:** if a second passage elsewhere also supports a fact, it may be added, but recall is measured only over the labeled quotes, so missing alternatives lower no score (§7.4).
- **Who labels:** Claude drafts the core set from the full text of both papers; the product owner (or a delegate) reviews every row before merge. The checker must pass.

### 5.5 Core set plan

About 30 rows, all asked as learner 2. "Limited" means `documents` names one paper, so decline correctness scores the uncovered ones.

| Category | Rows | Planned questions (W = WikiSkill, J = JevAgentHarness) |
|---|---|---|
| `single_hop` | 9 (30%) | W: the three workspace layers; what rollback keeps; traces sampled per iteration; *false premise:* how WikiSkill picks which skill to retrieve (it injects all of them). J: what a decision model is; who decides in cascade mode; decision-model latency vs a Flash call; DecisionGym's tool mix; *false premise:* can a decision-model guard be a security boundary (no) |
| `multi_hop` | 6 | W: why the inference agent can't read the wiki, with the ablation numbers (p. 5 + p. 11); optimizer cost vs EvoSkill (pp. 22–23). J: how AgentDecision-4B was trained and which stage mattered (p. 5 + p. 7); coding agents' savings vs the customer-service agent's (p. 7 + p. 9). Both: the benchmark both papers evaluate on and how each used it. Conversation: "what is the cascade mode?" then "what thresholds did it end up using?" |
| `unanswerable` | 5 | Limited to W: GPU hours of the evolution runs (not reported). Limited to J: a WebArena score (never evaluated); how Reflexion stores feedback between trials (only cited). Unlimited: W's HumanEval pass@1 (not a WikiSkill benchmark); learner 2 asking how Reflexion uses verbal feedback (cited by both papers, held by learner 1 only) |
| `out_of_scope` | 2 | "Write me a cover letter for a machine-learning job"; "Book me a train to Da Nang on Friday" |
| `conflicting` | 2 | Gemini 3.5 Flash alone on ALFWorld: 85.9% (W) vs 88.8% (J), asked two ways: "How well does Gemini 3.5 Flash do on ALFWorld without help?" (the conflict is implicit) and "Do the two papers agree on Gemini 3.5 Flash's ALFWorld baseline?" (explicit) |
| `time_sensitive` | 2 | J: "Which frontier models are the latest?" (dated to the paper); J: "How much does a JEV call cost?" ($0.042 per million input tokens on the run dates) |
| `near_miss` | 4 | J: how much cheaper the DecisionGym agent ran with AgentDecision-4B (gold 86.3%; distractors 81.1% in the Stage-2 test and the "81.1–89.0%" range). J: success lost when JEV made every tool choice (gold 19.0 points; distractor: the fixed 0.5 threshold's 21.5). W: Qwen-3.6-27B's average gain from WikiSkill over no skills (gold +23.9; distractor: +10.0 over the strongest competing method). Uncovered: learner 2 asking ReAct's own benchmarks, where both papers' ReAct mentions are the distractors |
| **Total** | **30** | Single-hop at 30%; every row hand-checked by the checker (§6) |

**All new rows start as `splits: [full]`; smoke is unchanged** (my call). Smoke already holds the 24 hand-written rows plus generated rows up to `SMOKE_SIZE` (30), and smoke gates every agent PR on the existing targets, so new rows there would break the size cap and could turn PRs red before any baseline exists. After the baseline the product owner picks which gold rows move into smoke, and in the same change decides what makes room (retiring existing rows or raising `SMOKE_SIZE` and the runbook's limit).

## 6. Evidence checker

`backend/evals/evidence.py` (needs the ingest extra) with a command, `uv run --extra eval --extra ingest python -m evals.evidence`, run before every dataset change and in the #359 PR:

1. Loads `ask.yaml` and the manifest, downloads the needed seed PDFs (`evals.corpus.download`), and builds each paper's page texts and worker chunks exactly as the worker does (`evals.chunks`).
2. **Normalization**, the same everywhere quotes are matched: Unicode NFKC, lower case, then keep only `[0-9a-z]`. This absorbs pypdf's missing spaces, line-break hyphens, small-caps splits ("DECI -SION GYM"), and math-italic letters, and is still exact for a 200-character quote.
3. For each quote: fails unless the normalized quote is a substring of its stated page's normalized text; fails unless at least one worker chunk contains it whole; prints the chunk ids (`<seed id>:<seq>`) that do.
4. Schema rules from §5.1 that code can check: evidence sources within `sources`, quote length (evidence and distractors), nugget evidence indexes in range, no `answer`/`nuggets`/`evidence` on uncovered rows, `distractors` present on `near_miss` rows, a distractor quote that never contains a gold quote, a known `category`, `type`, and `difficulty`, and the category–difficulty pairings of §5.3.
5. Prints the category and difficulty mix, and fails when `single_hop` rows exceed 40% of the gold rows (the "about a third" rule with some slack) or a difficulty level holds less than 20%.
6. Reports each question's word overlap with its quotes.
7. Exits 1 on any failure.

Pure functions (normalization, containment, schema problems) get unit tests that need no PDF. The checker itself needs the downloaded PDFs, so CI doesn't run it; the reviewer does, and the PR shows its output.

## 7. Metrics

Each metric is not applicable to rows that lack the labels it reads; §7.1–7.3 and §7.5 also skip uncovered rows.

### 7.1 `evidence.retrieved_recall` (code)

The share of the row's quotes found in the chunks the last turn retrieved (`outputs.chunks[*].text`): a quote is found when its normalized text is a substring of a chunk's normalized text. A run that failed before searching scores 0.

### 7.2 `evidence.cited_recall` (code)

The same over the chunks the answer cites (`outputs.citations[*].chunk_id`, looked up in `outputs.chunks`). This is the honest "the tutor showed the learner the right passage" signal.

### 7.3 `evidence.gold_rank` (code, position)

The reciprocal rank of the first retrieved chunk that holds a gold quote (1 when it is first, 0.5 second, …; 0 when none is retrieved). The mean is MRR. It shows position effects: the answer being retrieved but buried under similar chunks.

### 7.4 `evidence.distractor_cited` (code, noise; lower is better)

On rows with `distractors`, covered or not: 1 when the answer cites a chunk that holds a distractor quote and no gold quote, else 0. On an uncovered near-miss row, any citation of a distractor counts. The mean is the share of near-miss rows where noise won.

### 7.5 `answer_correctness` (judge, supported nugget recall)

One call to the `judge` model role per row, rubric `evaluators/rubrics/answer_correctness.md`, same openevals setup as `answer_relevance`. The judge sees the question (with earlier questions on follow-ups), the answer with its `[n]` markers, the text of each cited chunk by its `n`, and the nuggets. For each nugget it decides **stated** (the answer says it, in any words, without contradicting it) and **supported** (a sentence stating it carries a citation whose chunk supports it). Score = supported nuggets / all nuggets, with a comment listing the missed ones. A decline on a covered row scores 0.

The judge gets nuggets, not quotes: quotes would let it match strings instead of reading the answer. Whether a cited chunk holds the evidence is also visible in `evidence.cited_recall`.

For `conflicting` and `time_sensitive` rows the nuggets encode the expected behavior ("the two papers report different numbers", "as of the paper"), so the same metric scores it.

### 7.6 What is deliberately not measured

**Precision** of retrieved or cited chunks: labels are incomplete (another passage may also answer), so precision against them would punish correct retrieval. `retrieval_relevance` keeps covering noise.

### 7.7 Gating

- No thresholds at first: the gate lists the five new metrics as "no threshold", which never fails a run (`gate.py`).
- The new rows are in the full split only (§5.5), so PR smoke runs are unchanged. In full runs they are also scored by the existing evaluators and will likely lower `answer_relevance`, `retrieval_relevance`, and decline metrics: that is intended, since they are harder than the current rows.
- **Breakdown:** the run output and the CI job summary gain a section after the gate table with each of the five new metrics' means per `difficulty` and per `category` (and the row count behind each). It is not part of the gate: no thresholds, never fails. For that, `dataset.load_dataset` keeps each hand-written row's `metadata` and publishes it with the Langfuse item, version comparison includes metadata (so relabeling a row's category or difficulty makes a new version), and the runner keeps each score's row metadata alongside the flat per-metric list the gate reads. Langfuse's own filtering on item metadata then works too.
- Two full-split runs make the baseline; their means go on #359, and the product owner sets targets in `thresholds.yaml` and PRD §10.1 in a follow-up.
- The judge metric is read as a run mean. Each week the reviewer audits a sample of `answer_correctness` comments in the annotation queue (PRD §10.2); below ~80% agreement the rubric is revised.

## 8. Blind share

Hand-written rows are in the repo, so anyone tuning prompts can read their nuggets. The blind share is the **accepted generated rows** from the scale-up slice: they are published to Langfuse only and never committed. They come from the annotation queue, which already exists, so no new storage is needed. Target: about 20% of all gold rows blind once the scale-up lands. Until then there is no blind share. This slice accepts that, because its 26 rows are a start, not the gate. Langfuse access to the evals project stays limited to reviewers.

## 9. Scale-up slice (later ticket, outline only)

- `evals/generators/ask.py` gains a target difficulty next to the question type (the §5.3 factors become instructions, e.g. "paraphrase" or "pick a table passage"), and asks the judge model, in the same structured call, for the question plus a draft `answer`, `nuggets`, and short quotes taken from the given passages.
- Code keeps a draft only if every quote is found (normalized) in the passages it was written from, so generated evidence is verbatim by construction. Chunk ids stay in `chunks`.
- The reviewer accepts or rejects in the annotation queue as today; the rubric shown in the queue gains "the answer and nuggets are supported by the evidence".
- Its own ticket under #220, after #359 merges.

## 10. Decisions for the product owner

1. **Licence:** accept JevAgentHarness under CC BY-NC-SA 4.0 for short quoted excerpts in the eval dataset (my call: yes, with attribution in the manifest). If not, replace it with a CC-BY paper and keep the method.
2. **Blind share:** about 20% of gold rows, from generated and accepted rows only, starting with the scale-up slice (my call).
3. **No thresholds** for the new metrics until two baseline runs (my call).
4. **Expected behavior for conflicting and dated claims is product behavior** the PRD doesn't state yet: "when the learner's documents disagree, say so and cite each side" and "date a claim tied to a time ('as of the paper')". The #359 PR adds both to PRD §9.2's answer step if the product owner agrees (my call: agree; the eval then shows whether the agent already does it).
5. **Superseded documents and changed answers** (the expert's "one is superseded" and "the answer changed" cases) need a version pair in the corpus. Proposed later: add a preprint/published pair, as the manifest's target shape already plans (PRD §10.3), in its own ticket. Not in #359.
6. **Out-of-scope rows fail while the topic check is off.** They are kept so the gap stays visible; `correctly_declined`'s gate is temporarily 0.00 (#344), so they don't fail the run (my call).

## 11. Left to the builder

- Module and function names, and how the evaluators share the normalization (one module).
- The exact rubric wording for `answer_correctness`, within §7.3.
- Whether `Example` gains a `splits` field or the loader carries it in metadata, as long as `publish.split_examples` honours it and canonical comparison of versions ignores it.
- The ask.yaml header text and the `backend/evals/README.md` "Datasets" section.
- PRD changes in the #359 PR: §10.1 rows for the five metrics (target "set after baseline"); §10.3 item 1 (hand-written rows carry evidence quotes, a reference answer, nuggets, and one of the seven categories); §9.2's answer step for conflicting and dated claims if decision 4 holds; version bump.
