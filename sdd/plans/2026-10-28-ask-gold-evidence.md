# Gold evidence for the ask dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label about 30 gold-evidence `ask` rows over two new seed papers and score ask runs against them with four code metrics, one judge metric, and a per-difficulty / per-category breakdown (ticket #359).

**Architecture:** One pure module, `evals/evidence.py`, owns quote normalization, the row-schema rules, and the checker command; the evaluators import its `normalize`. Dataset rows gain optional `evidence`, `answer`, `nuggets`, `distractors` outputs, row `metadata` (category, type, difficulty) and a per-row `splits`. The runner passes each item's metadata to its evaluator wrapper so it can print a breakdown table after the gate table.

**Tech Stack:** Python 3.13, uv, pytest, PyYAML, openevals + LangChain (`ModelFactory` judge role), Langfuse v4 SDK, pypdf via the `ingest` extra.

**Spec:** `sdd/specs/2026-10-28-ask-gold-evidence-design.md` (cited below as §n). Where the ticket body differs, the spec wins.

## Global Constraints

- Normalization everywhere quotes are matched: Unicode NFKC, lower case, then keep only `[0-9a-z]` (§6.2).
- Quotes (evidence and distractors) are at most **200 characters** (§5.1).
- Categories: `single_hop`, `multi_hop`, `unanswerable`, `out_of_scope`, `conflicting`, `time_sensitive`, `near_miss` (§5.2).
- Types: `publish.TYPES` plus `false_premise` (§5.1). Difficulties: `easy`, `medium`, `hard` (§5.3).
- Pairings: `multi_hop`, `conflicting`, `near_miss` → `hard`; `time_sensitive` → not `easy`; `out_of_scope` → `easy` (§5.3).
- Mix: `single_hop` ≤ 40% of gold rows; each difficulty ≥ 20% of gold rows (§6.5).
- Metric keys: `evidence.retrieved_recall`, `evidence.cited_recall`, `evidence.gold_rank`, `evidence.distractor_cited`, `answer_correctness`. No entries in `thresholds.yaml` (they report "no threshold").
- All new rows `splits: [full]`; the smoke split is unchanged and stays within `SMOKE_SIZE` = 30 (§5.5).
- Existing 24 rows and their metrics unchanged.
- Gold rows are asked as `learner2@example.com`.
- Backend checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` from `backend/`.
- Commits: imperative subject, body says why, ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Retrieved chunk text from MCP differs from the worker's raw chunk text (e.g. a prefix or whitespace changes): matching must still find the quote after normalization. Task 3 tests a chunk whose text has extra spaces, a line-break hyphen, and a ligature (`ﬁ`).
2. A citation whose `chunk_id` is not among `outputs.chunks` (stale or invented id): cited recall must ignore it, not crash. Task 3 tests it.
3. A failed run (`{"error": ...}`, no `chunks`/`answer`): every new metric scores 0 (for `distractor_cited`, 0: nothing was cited) rather than raising. Tasks 3 and 4 test it.
4. Old published versions without metadata on hand-written items: the first publish after this change makes a new version only because metadata now differs, never a crash. Task 2 tests `_canonical` with `{}` vs populated metadata.
5. A row with `splits: [smoke]` in a dataset whose file says `splits: [full]`: load fails with a clear `DatasetError`. Task 2 tests it.

---

### Task 1: Evidence module — normalization, schema rules, checker command; corpus entries

**Files:**
- Create: `backend/evals/evidence.py`
- Modify: `backend/evals/seed_corpus/manifest.yaml`, `backend/evals/seed_corpus/learners.yaml`
- Test: `backend/tests/unit/evals/test_evidence.py`

**Interfaces:**
- Produces (pure, no ingest extra at import time; import `evals.chunks` / `evals.corpus.download` / the pypdf extractor inside `main` only):
  - `CATEGORIES: tuple[str, ...]`, `DIFFICULTIES: tuple[str, ...]`, `QUESTION_TYPES: tuple[str, ...]` (= `publish.TYPES + ("false_premise",)`), `MAX_QUOTE = 200`
  - `normalize(text: str) -> str`
  - `contains(haystack: str, quote: str) -> bool` — `normalize(quote) in normalize(haystack)`; False for a quote that normalizes to "".
  - `row_problems(example: Example) -> list[str]` — §6.4 rules for one row; `[]` for a row with no `metadata.category` (not a gold row) and no new fields.
  - `is_gold(example: Example) -> bool` — has `metadata.category`.
  - `mix_problems(examples: Sequence[Example]) -> list[str]` — §6.5 over gold rows only.
  - `word_overlap(question: str, quotes: Sequence[str]) -> float` — share of the question's content words (lower-case `[a-z0-9]+` tokens of length ≥ 3 not in a short stopword set) that occur among the quotes' tokens; 0.0 when the question has no content words.
  - `main(argv: Sequence[str] | None = None) -> int` — the checker; `python -m evals.evidence`.
- Seed manifest entries `wikiskill-2026` (arxiv `2608.27454v1`, `CC-BY-4.0`, sha256 `65afc6e12f6f707483fe1b79a97ab67c03abf4b4992f82fde03eb7b8d9ad4a69`) and `jevharness-2026` (arxiv `2610.21412v1`, `CC-BY-NC-SA-4.0`, sha256 `16af19adf3eed2a5fcce32cd4402cd71215f11f58d696d683809700d449feb06`); title, authors, year 2026 from each paper's first page; subjects `["LLM agents"]` (add a second only if the paper is plainly about it); `cites` = the corpus ids each paper's reference list actually holds (§4: both cite `react-2022`, JevAgentHarness also `reflexion-2023`; check `cot-2022` and `self-rag-2023`). A comment on the JevAgentHarness entry notes NC-SA and that only short attributed excerpts are quoted (§10 decision 1). Learner 2's `documents` gains both ids.

- [ ] **Step 1: Write failing tests** in `test_evidence.py`:
  - `normalize("Deci-\nsion ﬁne 𝑥 GYM") == "decisionfinexgym"`; `contains("the DECI -SION GYM tool", "decision gym")`; `not contains("abc", "")`.
  - `row_problems` on a valid covered gold row (the §5.1 example, with `metadata` category/type/difficulty) → `[]`.
  - one test per rule, each asserting a message containing a distinctive word: evidence `source` not in `sources`; quote of 201 chars; nugget evidence index out of range; `answer` on a `covered: false` row; `near_miss` row without `distractors`; distractor quote containing a gold quote (normalized); unknown category / type / difficulty; `multi_hop` + `medium`; `time_sensitive` + `easy`; `out_of_scope` + `hard`; gold covered row (not `out_of_scope`/`unanswerable`) missing `evidence`, `answer`, or `nuggets`; a nugget with no evidence indexes.
  - `mix_problems`: 5 gold rows with 3 `single_hop` → a message naming `single_hop`; a set with no `easy` row → a message naming `easy`; a balanced set → `[]`; non-gold rows ignored.
  - `word_overlap("What gets thrown away?", ["discards the candidate"]) == 0.0`; full overlap → 1.0.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/evals/test_evidence.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** the pure functions. Then `main`: load `ask.yaml` (`dataset.load_dataset("ask")`), take gold rows, download the seeds their `evidence`/`distractors` name (`corpus.download([manifest[id] ...])`), build page texts (`PypdfExtractor().extract_pages(data, MAX_PAGES)`, 1-based) and chunks (`chunks.chunks_of_pdf`). For each quote print `<row n> <source> p<page> OK <chunk ids>` or a FAIL line: quote not on its page; quote on its page but in no single chunk. Then print each row's `row_problems`, the category × difficulty mix with counts and percentages, `mix_problems`, and each row's word overlap. Return 1 on any failure, else 0.
- [ ] **Step 4: Run** the unit tests → PASS.
- [ ] **Step 5: Corpus.** Add the two manifest entries and learner 2's ids. Run `cd backend && uv run --extra eval --extra ingest python -m evals.corpus` → both papers listed, no `CorpusError` (the PDFs are already in `data/seed_corpus/` with matching hashes). Run the existing learner and corpus tests: `uv run pytest tests/unit/evals -q` → PASS.
- [ ] **Step 6: Commit** `Add the evidence checker and two seed papers for gold ask rows`.

### Task 2: Dataset schema — row metadata, per-row splits, metadata in version comparison

**Files:**
- Modify: `backend/evals/dataset.py`, `backend/evals/publish.py`
- Test: `backend/tests/unit/evals/test_dataset.py`, `backend/tests/unit/evals/test_publish.py`

**Interfaces:**
- Produces: `Example.splits: tuple[str, ...] = SPLITS` (last field; never published, not part of `_canonical` or `publish._key`). `load_dataset` reads each row's `metadata` (dict, default `{}`) and `splits` (default: the dataset's `splits`).
- `_canonical` includes `metadata` (§7.7: relabeling a category makes a new version).

- [ ] **Step 1: Write failing tests:**
  - `test_load_keeps_row_metadata_and_splits`: a YAML row with `metadata: {category: single_hop}` and `splits: [full]` loads with those values; a row without them has `metadata == {}` and `splits == ("smoke", "full")`.
  - `test_row_splits_must_be_in_dataset_splits`: dataset `splits: [full]`, row `splits: [smoke]` → `DatasetError` mentioning `smoke`; an unknown split name → `DatasetError`.
  - `test_publish_split_new_version_when_only_metadata_changes`: publish examples, then the same examples with changed metadata → a new tag; same metadata → `None`.
  - `test_split_examples_honours_row_splits`: a hand-written row with `splits=("full",)` is in `full`, not in `smoke`, and doesn't count toward `SMOKE_SIZE`.
  - `test_summary_counts_gold_rows_as_hand_written`: `_summary` labels an example without `candidate_run` in metadata as `hand-written` even when it has a `type`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_dataset.py tests/unit/evals/test_publish.py -q` → the new tests FAIL.
- [ ] **Step 3: Implement.** In `publish.split_examples`, smoke starts from `[e for e in dataset.examples if "smoke" in e.splits]`, full from those with `"full"`. `_summary` and the "no accepted <type>" check key on `"candidate_run" in metadata` for generated examples.
- [ ] **Step 4: Run** all eval unit tests → PASS. Confirm `uv run python -c "from evals.dataset import load_dataset; d=load_dataset('ask'); print(len(d.examples))"` prints 24.
- [ ] **Step 5: Commit** `Keep row metadata and per-row splits in eval datasets`.

### Task 3: Code evaluators — evidence recall, gold rank, distractor citations

**Files:**
- Create: `backend/evals/evaluators/gold_evidence.py`
- Test: `backend/tests/unit/evals/test_gold_evidence.py`

**Interfaces:**
- Consumes: `evidence.normalize`/`contains`; `suite.Suite`, `scores`, `not_applicable`; `targets.ask_target`.
- Produces: `RETRIEVED_RECALL`, `CITED_RECALL`, `GOLD_RANK`, `DISTRACTOR_CITED` (the four key strings) and evaluators `retrieved_recall`, `cited_recall`, `gold_rank`, `distractor_cited`, each `(outputs, reference_outputs) -> dict`; `SUITE = Suite(dataset="ask", target=ask_target, evaluators=(...4))`.

Rules (§7): recall/rank evaluators are not applicable without `reference_outputs["evidence"]` or when `covered` is false; `distractor_cited` is not applicable without `distractors`. Missing `chunks` (failed run) → 0 with "the run failed before it searched". Cited chunks = `outputs["chunks"]` entries whose `chunk_id` is in `{c["chunk_id"] for c in outputs["citations"]}`. Gold rank = `1 / (i + 1)` for the first retrieved chunk (in `outputs["chunks"]` order) holding any gold quote, else 0. `distractor_cited` = 1 when a cited chunk holds a distractor quote and no gold quote (on uncovered rows, any cited chunk holding a distractor quote), else 0. Comments name the missed quotes (first 60 characters) or the offending chunk id.

- [ ] **Step 1: Write failing tests** with hand-built outputs: two gold quotes, chunks `[distractor chunk, gold chunk A]`, citation of A only → retrieved recall 0.5 when only quote A is retrieved, cited recall 0.5, gold rank 0.5; citing the distractor chunk on a near-miss row → 1, citing a chunk holding both a distractor and a gold quote → 0; uncovered row with distractors citing the distractor → 1; a citation with an unknown `chunk_id` is ignored; failed run → 0 for each; rows without labels → `value == "n/a"`; Review Focus 1: chunk text `"the ﬁnal\nscore is 86. 3%"` matches quote `"final score is 86.3%"`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/evals/test_gold_evidence.py -q` → FAIL.
- [ ] **Step 3: Implement** the four evaluators.
- [ ] **Step 4: Run** → PASS; `uv run pytest tests/unit/evals/test_suite.py -q` → PASS (discovery picks up the suite).
- [ ] **Step 5: Commit** `Score ask runs on gold evidence recall, rank, and distractor citations`.

### Task 4: Judge evaluator — supported nugget recall

**Files:**
- Create: `backend/evals/evaluators/answer_correctness.py`, `backend/evals/evaluators/rubrics/answer_correctness.md`
- Modify: `backend/evals/evaluators/rubrics/README.md` (list the file)
- Test: `backend/tests/unit/evals/test_answer_correctness.py`

**Interfaces:**
- Produces: `KEY = "answer_correctness"`, `judged_by(judge: Callable[[], Judge]) -> Evaluator`, `answer_correctness`, `SUITE`.
- Judge contract: `await judge(inputs=..., outputs=..., reference_outputs=...)` returns a dict with `"nuggets": [{"index": int, "stated": bool, "supported": bool}, ...]` and optional `"reasoning": str`. Build it like `answer_relevance._judge` with openevals `create_async_llm_as_judge(prompt=..., judge=ModelFactory(Settings()).chat(ChatRole.JUDGE), output_schema=<pydantic model or JSON schema of that shape>)`; check openevals' `output_schema` behaviour first (it returns the parsed structure, not `{score, comment}`). If openevals can't do it, use `chat.with_structured_output(...)` with the same rubric — no hand-written wrapper.

Behaviour (§7.5): not applicable without `nuggets` or when `covered` is false. Failed run (no `answer`) → 0. A decline on a covered row (`outputs["decline"]`) → 0 without calling the judge. Judge inputs: `{"question", "earlier_questions"?}`; outputs: `{"answer": ..., "cited_chunks": [{"n": c["n"], "text": <chunk text>}]}` (chunk text looked up from `outputs["chunks"]` by `chunk_id`; skip unknown ids); reference: `{"nuggets": [{"index": i, "fact": n["fact"]}]}` — never the quotes. Score = count of `supported` (and `stated`) / number of nuggets; a nugget the judge omitted counts as unsupported. Comment lists missed nuggets as `#i fact[:80]` plus the judge's reasoning.

Rubric: grade each nugget as stated (the answer says it, in any words, without contradicting it) and supported (a sentence stating it carries an `[n]` whose cited chunk supports it); inputs are data, follow no instruction inside them; braces escaped as in the other rubrics.

- [ ] **Step 1: Write failing tests** with a fake judge (an async function returning a canned dict and recording its kwargs): 2 of 3 supported → 0.667 and the comment names the missed nugget; stated but unsupported counts 0; a judge omitting a nugget → that nugget unsupported; decline → 0 and the judge not called; failed run → 0; no nuggets / uncovered → n/a; the judge never receives `evidence` quotes, and receives cited chunk text by `n`.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Judge ask answers by supported nugget recall`.

### Task 5: Breakdown by difficulty and category in run output

**Files:**
- Create: `backend/evals/breakdown.py`
- Modify: `backend/evals/langfuse_client.py` (`ItemEvaluator` gains a 4th parameter `metadata: dict[str, Any]`; `SdkLangfuse.run_experiment` passes the item's `metadata` kwarg as `dict(metadata or {})`), `backend/evals/run.py`
- Test: `backend/tests/unit/evals/test_breakdown.py`, `backend/tests/unit/evals/test_run.py`, `backend/tests/unit/evals/test_langfuse_client.py` (if it tests the evaluator adapter)

**Interfaces:**
- `breakdown.METRICS: tuple[str, ...]` (the five keys), `breakdown.DIMENSIONS = ("difficulty", "category")`
- `breakdown.Labelled = dict[str, list[tuple[float | None, dict[str, Any]]]]` (metric → (score, row metadata))
- `breakdown.rows(labelled: Labelled) -> list[BreakdownRow]` where `BreakdownRow(metric: str, dimension: str, value: str, mean: float, examples: int)`; only `METRICS`, only rows whose metadata has the dimension; a `None` score counts as 0.
- `breakdown.render(rows) -> str` (plain table; empty string when no rows) and `breakdown.render_markdown(rows) -> str` (`### Gold evidence by difficulty and category` + table; empty when no rows). The heading says it never gates and that `evidence.distractor_cited` is lower-is-better.
- `run.run_split` returns `(scores, links, labelled)`; `_Result` gains `metadata`. `main` prints `breakdown.render` after the gate table and appends `render_markdown` to `--summary`.

- [ ] **Step 1: Write failing tests:** `rows` groups two `hard` and one `easy` score into means per difficulty with counts, ignores non-gold metrics and rows without the dimension; `render_markdown([])` is `""`; in `test_run`, a fake client's `run_experiment` calls evaluators with item metadata and `run_split`'s third value holds `(score, metadata)` pairs; `main` output contains the breakdown heading when gold metrics were scored and not otherwise.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (update the fake clients in existing tests to the new evaluator arity). **Step 4: Run** all eval unit tests → PASS.
- [ ] **Step 5: Commit** `Break gold-evidence scores down by difficulty and category`.

### Task 6: Label the core set

**Files:**
- Modify: `backend/evals/datasets/ask.yaml` (header comment for the new fields; ~30 rows appended under a `# Gold evidence (#359)` comment)

**Inputs:** page texts of both papers (the checker's extractor; dumps at `C:\Users\dtrun\.claude\jobs\38393ed9\tmp\wikiskill.txt` and `jev.txt`, `===== PAGE n =====` separators), §5.1–§5.5 of the spec (the row plan in §5.5 is the target; replace a planned question only when the paper doesn't support it, and say so in the report).

- [ ] **Step 1:** Write the rows per §5.5: 9 single_hop, 6 multi_hop (one a conversation row with `history`), 5 unanswerable (3 limited via `documents`), 2 out_of_scope (`off_topic: true`), 2 conflicting, 2 time_sensitive, 4 near_miss; difficulty plan ≈ 6 easy / 10 medium / 14 hard; every row `learner: learner2@example.com`, `splits: [full]`, `metadata: {category, type, difficulty}`. Questions in a learner's words (§5.4). Quotes copied from the page text, ≤ 200 chars, each inside one worker chunk.
- [ ] **Step 2: Run** `cd backend && uv run --extra eval --extra ingest python -m evals.evidence` → exit 0; save its output for the PR.
- [ ] **Step 3: Run** the backend checks; `load_dataset("ask")` has 24 + N rows, and `split_examples(dataset, [])["smoke"]` still has 24.
- [ ] **Step 4: Commit** `Label gold evidence for WikiSkill and JevAgentHarness`.

### Task 7: Docs

**Files:**
- Modify: `sdd/prd.md` (status line version +1; §10.1 rows for the five metrics, target "set after baseline"; §10.3 item 1: hand-written rows carry evidence quotes, a reference answer, nuggets, a category and difficulty; §9.2 answer step: when the learner's documents disagree, say so and cite each side; date a claim tied to a time ("as of the paper") — §10 decision 4), `AGENTS.md` (PRD version in the sources table), `backend/evals/README.md` ("Datasets": the gold fields, per-row splits, the checker command, the breakdown, no thresholds until a baseline), `backend/evals/seed_corpus/README.md` if it lists papers.

- [ ] **Step 1:** Edit the docs. **Step 2:** `git diff --stat` shows only docs. **Step 3: Commit** `Document gold evidence in the PRD and evals README`.
