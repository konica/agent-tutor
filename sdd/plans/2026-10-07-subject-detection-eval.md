# Subject-Detection Eval Implementation Plan (#86)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LangSmith eval measures first-turn subject detection on the seed corpus (exact_set, contains_wrong, asked_when_clear), is gated by `thresholds.yaml`, and drives tuning of `detect_threshold`, `detect_margin`, `multi_margin` until a smoke-split run meets the Release 1 targets.

**Architecture:** The eval runs the real `SubjectDetector` and `DetectionPolicy` against an in-process `Retriever` over the seed corpus. That corpus is chunked with the production chunker and embedded with the production embedding model (via `ModelFactory`), and cached under `data/seed_corpus/index/`. Scores are exact cosine similarity, which is what pgvector's `1 - cosine_distance` returns. A generator builds synthetic learners (subsets of seed documents) and asks the judge model to write labeled first questions. The dataset is committed as YAML so it gets a human review in the PR (PRD §10.3 step 6), and `run.py` syncs it to a LangSmith dataset with `smoke`/`full` splits. Per-subject scores don't depend on the thresholds, so tuning is an offline grid sweep over one run's scores.

**Tech Stack:** Python 3.13, LangSmith SDK 0.14 (`evaluate`, dataset splits), numpy, PyYAML, LangChain (`ModelFactory`), pytest.

**Spec:** Ticket #86 (`gh issue view 86`), PRD `sdd/prd.md` §9.2 step 1 (detection rule), §10.1 "Subject detection", §10.3 items 2 and 6; `backend/evals/thresholds.yaml` → `release_1.subject_detection`.

## Design decisions

- **Metric definitions** (PRD §10.1 says "exactly correct / contains a wrong subject / asked when clear"). Each item is *clear* (one right subject set) or *ambiguous* (the question straddles the listed subjects, so asking is right). The detector "asked" when `Detection.unsure` is true.
  - `exact_set` — clear items only: did not ask and bound exactly the expected set.
  - `asked_when_clear` — clear items only: asked.
  - `contains_wrong` — all items: did not ask and bound a subject outside the expected set.
- **Labels follow detection's mechanics.** A chunk carries every subject of its document, so a question from a document tagged {A, B} scores A and B equally. Its expected set is therefore the source document's subjects. A multi-subject item's expected set is the union of its two source documents' subjects (≤ 3).
- **In-process retriever, not the Compose stack.** Detection quality depends on the embeddings, the chunker, and the policy, not on the MCP transport or `can_read` (isolation tests cover those). Exact search is used; HNSW recall is measured by the separate filtered-recall eval.
- **The dataset is YAML in the repo**, synced to LangSmith on each run: examples are matched by `metadata.item_id`, with missing ones added, changed ones updated, and removed ones deleted. LangSmith versions every change. Smoke items carry splits `["smoke", "full"]`, the others `["full"]`.
- **The policy comes from SSM** (`load_detection_policy`, the agent's code path; LocalStack locally), so a run measures what the agent would use. `--policy T,M,MM` overrides it for experiments.
- **Seed corpus:** arXiv papers whose arXiv license is CC BY 4.0 (checked via arXiv OAI-PMH `<license>`), across four overlapping subjects. The download step pins version and SHA-256.

## Global Constraints

- Read `AGENTS.md` and `backend/AGENTS.md` first. Eval code lives in `backend/evals/` (package `evals`), may import any `smart_tutor` module, and is not imported by `smart_tutor`.
- Checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. mypy covers only `src/`; still type-annotate eval code.
- Unit tests for eval code go in `backend/tests/unit/evals/` and use fakes (`from fakes import fake_embeddings, fake_chat_model`). No network, no Bedrock, no LangSmith in unit tests. `pyproject.toml` `[tool.pytest.ini_options] pythonpath` becomes `["tests", "."]` so tests can `import evals`.
- Paths: repo root = `Path(__file__).resolve().parents[2]` from a module directly in `backend/evals/`. PDFs go in `<repo>/data/seed_corpus/<id>.pdf`, the index cache in `<repo>/data/seed_corpus/index/` (`/data/` is git-ignored).
- Subject ids in the eval: `uuid.uuid5(SEED_NAMESPACE, name)` with `SEED_NAMESPACE = uuid.UUID("6f1c7d1e-5b7a-4d0e-9a39-6a3f3c2b9e10")`. Datasets and outputs use subject **names**.
- Threshold targets (`thresholds.yaml`): `exact_set` min 0.90, `contains_wrong` max 0.03, `asked_when_clear` max 0.10.
- Commit subjects in the imperative mood, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- A clear item where the detector is unsure (the asked fallback still lists the best subject in `subject_ids`) must count as asked, never as exact or wrong. Pinned in Task 1.
- An ambiguous item where the detector binds a subset of the expected set is not wrong; binding a subject outside it is. Pinned in Task 1.
- A learner library where a requested subject has no document must give that subject no score (absent, not 0). Pinned in Task 3.
- A downloaded PDF whose SHA-256 differs from the manifest must not be written and must fail loudly. Pinned in Task 2.
- A dataset item whose expected subjects are not all the learner's subjects, or whose learner has fewer than 2 subjects (detection is skipped), must be rejected when loading. Pinned in Task 4.

---

### Task 1: Detection metrics, threshold gate, and policy sweep

**Files:**
- Create: `backend/evals/evaluators/subject_detection.py`, `backend/evals/gate.py`, `backend/evals/tune_detection.py` (pure functions only in this task; the CLI comes in Task 5)
- Modify: `backend/pyproject.toml` (pytest `pythonpath = ["tests", "."]`)
- Test: `backend/tests/unit/evals/__init__.py` (empty), `backend/tests/unit/evals/test_subject_detection_metrics.py`, `backend/tests/unit/evals/test_gate.py`, `backend/tests/unit/evals/test_tune_detection.py`

**Interfaces:**
- Produces:
  - `evals.evaluators.subject_detection`: `METRICS = ("exact_set", "contains_wrong", "asked_when_clear")`; `item_scores(bound: Collection[str] | None, expected: Collection[str], clear: bool) -> dict[str, float]` (`bound=None` means asked; returns only the keys that apply to the item); `subject_detection(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> list[dict[str, Any]]` — LangSmith evaluator; `outputs = {"subjects": list[str], "unsure": bool, "scores": dict[str, float]}`, `reference_outputs = {"expected_subjects": list[str], "clear": bool}`; returns `[{"key": k, "score": v}, ...]`; `summarize(rows: Iterable[Mapping[str, float]]) -> dict[str, float]` — mean per key over the rows that have it.
  - `evals.gate`: `THRESHOLDS_PATH`; `load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]`; `targets(thresholds: Mapping[str, Any], release: str, suite: str) -> dict[str, tuple[str, float]]` (`{"exact_set": ("min", 0.9), ...}`); `failures(scores: Mapping[str, float], targets: Mapping[str, tuple[str, float]]) -> list[str]` (a missing score is a failure).
  - `evals.tune_detection`: `LabeledScores(scores: dict[str, float], expected: frozenset[str], clear: bool)` frozen dataclass; `measure(policy: DetectionPolicy, items: Sequence[LabeledScores]) -> dict[str, float]`; `slack(metrics, targets) -> float` (min over metrics of `value - min` or `max - value`; negative = missed); `sweep(items, targets, thresholds: Sequence[float], margins: Sequence[float], multi_margins: Sequence[float]) -> list[tuple[DetectionPolicy, dict[str, float], float]]`, sorted by slack desc, then exact_set desc, contains_wrong asc, then threshold, margin, multi_margin asc (deterministic).

- [ ] **Step 1: Write the failing tests**

`tests/unit/evals/test_subject_detection_metrics.py`:

```python
import pytest

from evals.evaluators.subject_detection import item_scores, subject_detection, summarize


@pytest.mark.parametrize(
    ("bound", "expected", "clear", "scores"),
    [
        (["A"], ["A"], True, {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A", "B"], ["A", "B"], True, {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A"], ["A", "B"], True, {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A", "C"], ["A"], True, {"exact_set": 0.0, "contains_wrong": 1.0, "asked_when_clear": 0.0}),
        (None, ["A"], True, {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 1.0}),
        (None, ["A", "B"], False, {"contains_wrong": 0.0}),  # ambiguous: asking is right
        (["A"], ["A", "B"], False, {"contains_wrong": 0.0}),  # a subset of the straddled subjects is not wrong
        (["C"], ["A", "B"], False, {"contains_wrong": 1.0}),
    ],
)
def test_item_scores(bound, expected, clear, scores) -> None:
    assert item_scores(bound, expected, clear) == scores


def test_unsure_counts_as_asked_even_though_the_best_subject_is_listed() -> None:
    results = subject_detection(
        {"subjects": ["A"], "unsure": True, "scores": {"A": 0.4}}, {"expected_subjects": ["A"], "clear": True}
    )
    assert {r["key"]: r["score"] for r in results} == {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 1.0}


def test_summarize_averages_each_key_over_the_items_that_have_it() -> None:
    rows = [{"exact_set": 1.0, "contains_wrong": 0.0}, {"exact_set": 0.0, "contains_wrong": 1.0}, {"contains_wrong": 0.0}]
    assert summarize(rows) == {"exact_set": 0.5, "contains_wrong": pytest.approx(1 / 3)}
```

`tests/unit/evals/test_gate.py`:

```python
from evals.gate import failures, load_thresholds, targets


def test_targets_read_release_1_subject_detection_from_the_real_file() -> None:
    assert targets(load_thresholds(), "release_1", "subject_detection") == {
        "exact_set": ("min", 0.90),
        "contains_wrong": ("max", 0.03),
        "asked_when_clear": ("max", 0.10),
    }


def test_failures_name_each_missed_or_missing_metric() -> None:
    goal = {"exact_set": ("min", 0.9), "contains_wrong": ("max", 0.03), "asked_when_clear": ("max", 0.1)}
    assert failures({"exact_set": 0.9, "contains_wrong": 0.03, "asked_when_clear": 0.1}, goal) == []
    found = failures({"exact_set": 0.89, "contains_wrong": 0.05}, goal)
    assert len(found) == 3 and all(any(m in f for m in goal) for f in found)
```

`tests/unit/evals/test_tune_detection.py`:

```python
from evals.tune_detection import LabeledScores, measure, slack, sweep
from smart_tutor.tutoring.domain.detection import DetectionPolicy

GOAL = {"exact_set": ("min", 0.9), "contains_wrong": ("max", 0.03), "asked_when_clear": ("max", 0.1)}
ITEMS = [
    LabeledScores({"A": 0.60, "B": 0.40}, frozenset({"A"}), True),
    LabeledScores({"A": 0.55, "B": 0.54}, frozenset({"A", "B"}), True),
    LabeledScores({"A": 0.45, "B": 0.44}, frozenset({"A", "B"}), False),
]


def test_measure_applies_the_policy_to_each_item() -> None:
    metrics = measure(DetectionPolicy(0.5, 0.1, 0.02), ITEMS)
    assert metrics == {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}


def test_measure_counts_a_too_high_threshold_as_asking() -> None:
    assert measure(DetectionPolicy(0.7, 0.1, 0.02), ITEMS)["asked_when_clear"] == 1.0


def test_slack_is_the_tightest_margin_to_a_target() -> None:
    assert slack({"exact_set": 0.95, "contains_wrong": 0.0, "asked_when_clear": 0.05}, GOAL) == 0.03


def test_sweep_ranks_policies_meeting_the_targets_first() -> None:
    ranked = sweep(ITEMS, GOAL, thresholds=[0.5, 0.7], margins=[0.1], multi_margins=[0.0, 0.02])
    best, metrics, best_slack = ranked[0]
    assert best == DetectionPolicy(0.5, 0.1, 0.02) and best_slack >= 0
    assert ranked[-1][2] < 0
```

- [ ] **Step 2: Run to verify they fail** — `cd backend && uv run pytest tests/unit/evals -q` → ImportError.

- [ ] **Step 3: Implement.** `item_scores`: `asked = bound is None`; `wrong = 0.0 if asked else float(not set(bound) <= set(expected))`; clear items also get `exact_set = float(not asked and set(bound) == set(expected))` and `asked_when_clear = float(asked)`. `subject_detection` passes `None if outputs["unsure"] else outputs["subjects"]`. `gate.targets` reads `thresholds[release][suite]`, each entry's `min` or `max` key. `failures` returns messages such as `"exact_set 0.87 < min 0.90"` / `"asked_when_clear missing"`. `measure` uses `policy.bind({SubjectId(k): v ...})` (the `SubjectId` NewType over str) and `summarize`. `sweep` builds every `DetectionPolicy(t, m, mm)` product.

- [ ] **Step 4: Run tests** → PASS; then the full check line.

- [ ] **Step 5: Commit** — "Score subject detection against labeled first questions".

### Task 2: Seed corpus manifest loader and verified download

**Files:**
- Create: `backend/evals/seed_corpus/__init__.py`, `backend/evals/seed_corpus/manifest.py`, `backend/evals/seed_corpus/download.py`
- Modify: `backend/evals/seed_corpus/README.md` (download command)
- Test: `backend/tests/unit/evals/test_seed_corpus.py`

**Interfaces:**
- Produces: `evals.seed_corpus.manifest`: `REPO_ROOT`, `MANIFEST_PATH`, `PDF_DIR = REPO_ROOT / "data" / "seed_corpus"`; `SeedDocument(id: str, source_type: str, source_ref: str, license: str, sha256: str, subjects: tuple[str, ...], title: str)` frozen dataclass with `url` property (`arxiv` → `https://arxiv.org/pdf/<ref>`, `url` → ref) and `pdf_path(pdf_dir: Path = PDF_DIR) -> Path` (`<pdf_dir>/<id>.pdf`); `load_manifest(path: Path = MANIFEST_PATH) -> list[SeedDocument]` raising `ValueError` on duplicate ids or 0 / more than 3 subjects. `evals.seed_corpus.download`: `ChecksumError(Exception)`; `download_all(docs: Sequence[SeedDocument], fetch: Callable[[str], bytes], pdf_dir: Path = PDF_DIR) -> list[str]` (ids fetched; skips files already matching; never writes a mismatch); `main()` for `python -m evals.seed_corpus.download` using `urllib.request` with a `User-Agent` header and a 3 s pause between arXiv fetches.

- [ ] **Step 1: Write failing tests** (temporary manifest YAML in `tmp_path`, the manifest schema from `manifest.yaml`'s header): loads fields; rejects duplicate ids; rejects 4 subjects; `download_all` writes a PDF whose bytes hash to `sha256`; skips an existing good file (fetch not called); raises `ChecksumError` and writes nothing on a mismatch; re-fetches an existing corrupt file.
- [ ] **Step 2:** run → fail. **Step 3:** implement. **Step 4:** run → pass + checks.
- [ ] **Step 5: Commit** — "Download the seed corpus and check each PDF's SHA-256".

### Task 3: Seed corpus index and in-process retriever

**Files:**
- Create: `backend/evals/corpus_index.py`
- Test: `backend/tests/unit/evals/test_corpus_index.py`

**Interfaces:**
- Consumes: `SeedDocument`, `load_manifest` (Task 2); `PdfExtractor` port (`extract_pages(data, max_pages) -> list[str]`); `build_chunker(ChunkingConfig()) -> (transformer, chunker_id)` from `smart_tutor.knowledge.adapters.chunking`; `Embeddings`; `Retriever`, `RetrievedChunk`.
- Produces: `SEED_NAMESPACE`; `subject_id(name: str) -> SubjectId`; `IndexedChunk(chunk_id: str, document_id: str, page: int, text: str)`; `CorpusIndex(documents: dict[str, SeedDocument], chunks: list[IndexedChunk], vectors: np.ndarray)` (rows L2-normalized, aligned with `chunks`); `build_index(docs, read_pdf: Callable[[SeedDocument], bytes], extractor: PdfExtractor, chunker: BaseDocumentTransformer, embeddings: Embeddings, max_pages: int = 500) -> CorpusIndex` (pages → `langchain_core.documents.Document(page_content, metadata={"page": n})` 1-based → chunker → `embeddings.embed_documents` per document, documents in a `ThreadPoolExecutor(max_workers=8)`; chunk id `"<doc id>:<i>"`); `load_or_build_index(docs, cache_dir: Path, key: str, build: Callable[[], CorpusIndex]) -> CorpusIndex` (cache = `<cache_dir>/<key>.npz` with vectors plus a JSON sidecar of chunks; `key` is a sha256 over chunker id, embedding model id, and each doc's id+sha256); `SeedCorpusRetriever(index: CorpusIndex, library: Sequence[str], embeddings: Embeddings)` implementing `Retriever.search`: embeds the query with `embed_query`, considers chunks of library documents having at least one requested subject, scores cosine (`vectors @ q/‖q‖`), returns top `k` nearest first as `RetrievedChunk(chunk_id, document_title=doc.title, page, text, score, subject_ids=sorted(requested ∩ doc's subject ids))`.

- [ ] **Step 1: Write failing tests** with `fake_embeddings()` and a fake extractor returning fixed pages: chunks get 1-based pages and stable ids; `vectors` rows have unit norm; a search over one subject never returns chunks of a document without it; hits' `subject_ids` exclude unrequested subjects of the document; a chunk whose text equals the query scores ≈ 1.0 and ranks first; documents outside `library` are never returned; a requested subject with no library document yields no hit carrying it (so `best_scores` leaves it absent); `load_or_build_index` calls `build` once and then loads an equal index from cache (`np.allclose`, same chunks).
- [ ] **Step 2–4:** fail → implement → pass + checks.
- [ ] **Step 5: Commit** — "Index the seed corpus for in-process detection runs".

### Task 4: Labeled detection dataset and its generator

**Files:**
- Create: `backend/evals/detection_dataset.py`, `backend/evals/generators/subject_detection.py`, `backend/evals/datasets/README.md` (what the YAML is, how to regenerate, that edits are reviewed in the PR)
- Test: `backend/tests/unit/evals/test_detection_dataset.py`, `backend/tests/unit/evals/test_detection_generator.py`

**Interfaces:**
- Consumes: `SeedDocument`, `load_manifest`; `CorpusIndex`, `IndexedChunk`.
- Produces:
  - `evals.detection_dataset`: `DATASET_PATH = backend/evals/datasets/subject_detection.yaml`; `DetectionItem(id: str, kind: Literal["single", "multi", "ambiguous"], smoke: bool, learner_documents: tuple[str, ...], question: str, expected_subjects: tuple[str, ...], source_chunks: tuple[str, ...])` with `clear` property (`kind != "ambiguous"`), `inputs()` → `{"question", "learner_documents": list}` and `reference_outputs()` → `{"expected_subjects": list, "clear": bool}`; `learner_subjects(item, docs: Mapping[str, SeedDocument]) -> list[str]` (sorted union); `load_items(split: Literal["smoke", "full"], path=DATASET_PATH, docs: Mapping[str, SeedDocument] | None = None) -> list[DetectionItem]` (`full` = all) validating unique ids, known document ids, 1–3 expected subjects all among the learner's, a learner with ≥ 2 subjects, ambiguous items with ≥ 2 expected subjects; `dump_items(items, path)`.
  - `evals.generators.subject_detection`: `Learner(id: str, documents: tuple[str, ...])`; `make_learners(docs: Sequence[SeedDocument], rng: random.Random, count: int) -> list[Learner]` (each learner holds 1–2 documents from each of 3–4 subjects, ≥ 2 subjects); `generate(index: CorpusIndex, learners, model: BaseChatModel, rng, counts: Mapping[str, tuple[int, int]]) -> list[DetectionItem]` where `counts[kind] = (smoke, full_only)`: single = one chunk of one document → expected = that document's subjects; multi = chunks from two learner documents with disjoint subjects and a union ≤ 3 → expected = union; ambiguous = same pairing, a short vague question that could be about either → expected = union, `clear` false. The prompts (constants `SINGLE_PROMPT`, `MULTI_PROMPT`, `AMBIGUOUS_PROMPT`) put passages in `<passage>` tags as quoted data, ask for one question a learner would type as the first message of a chat, no paper titles, no author names, no "this paper"/"the passage", and "Reply with the question only." The reply is stripped of whitespace, quotes, and any `<think>…</think>` block. Chunks under 300 characters are skipped (references and headers). `main()` (`python -m evals.generators.subject_detection --seed 86`) builds the index the same way Task 5's target does, uses `ModelFactory(Settings()).chat(ChatRole.JUDGE)`, and writes `DATASET_PATH`.

- [ ] **Step 1: Write failing tests:** `load_items` rejects each invalid case above and returns smoke items only for `"smoke"`; a round trip through `dump_items`/`load_items` is equal; `make_learners` learners always have ≥ 2 subjects; `generate` with `fake_chat_model` (responses `"<think>x</think> What is attention?"` etc.) produces the requested counts per kind with expected sets per the rules, each valid under `load_items` validation, and strips the think block.
- [ ] **Step 2–4:** fail → implement → pass + checks.
- [ ] **Step 5: Commit** — "Generate labeled first questions from the seed corpus".

### Task 5: Detection target, LangSmith run, and tuning CLI

**Files:**
- Modify: `backend/evals/targets.py` (keep `tutor_target` stub), `backend/evals/run.py`, `backend/evals/tune_detection.py` (add `main`), `backend/evals/README.md`, `Makefile` (`evals-smoke` unchanged; add `evals-tune-detection`, `seed-corpus`)
- Test: `backend/tests/unit/evals/test_detection_target.py`, `backend/tests/unit/evals/test_run.py`

**Interfaces:**
- Consumes: everything above; `SubjectDetector`, `DetectionPolicy`, `load_detection_policy`, `SsmParameterStore`, `ssm_client`, `Settings`, `ModelFactory`, `PypdfExtractor`.
- Produces:
  - `evals.targets`: `seed_index(settings: Settings) -> CorpusIndex` (manifest + verified PDFs + production chunker + `ModelFactory(settings).embedding()` + cache); `detection_target(index: CorpusIndex, embeddings: Embeddings, policy: DetectionPolicy) -> Callable[[dict[str, Any]], dict[str, Any]]` returning `{"subjects": [names], "unsure": bool, "scores": {name: score}}` via `SubjectDetector(SeedCorpusRetriever(index, inputs["learner_documents"], embeddings), policy).detect(question, [subject_id(n) for n in learner subjects])` run with `asyncio.run`.
  - `evals.run`: `DATASET_NAMES = {"subject_detection": "smart-tutor-subject-detection"}`; `plan_sync(local: Sequence[DetectionItem], remote: Sequence[RemoteExample]) -> SyncPlan(create: list[DetectionItem], update: list[tuple[str, DetectionItem]], delete: list[str])`, where `RemoteExample(id: str, item_id: str, inputs: dict, outputs: dict, splits: list[str])` compares inputs, outputs, and splits; `sync_dataset(client, name, items) -> None`; `run_subject_detection(split, policy_override: DetectionPolicy | None, client) -> tuple[dict[str, float], str]` (scores, experiment URL or name); `main()`: `--split`, `--policy T,M,MM`; prints scores, targets, the experiment link; exit 1 when `gate.failures` is non-empty.
  - `evals.tune_detection.main()`: `--split`; computes `LabeledScores` per item with the target's retriever and `best_scores` (no LangSmith), sweeps `thresholds = 0.20..0.80 step 0.01`, `margins = 0.000..0.150 step 0.005`, `multi_margins = 0.000..0.100 step 0.005`, prints the top 10 with their metrics and slack, and the current SSM policy's metrics.

- [ ] **Step 1: Write failing tests:** `detection_target` on a tiny `CorpusIndex` built with `fake_embeddings` returns subject **names**, `unsure` true for a too-high threshold, and scores keyed by name; `plan_sync` creates a new item, updates a changed question or split membership, deletes a remote item no longer local, and leaves equal ones alone.
- [ ] **Step 2–4:** fail → implement → pass + checks. `sync_dataset` uses `client.has_dataset`/`create_dataset`, `client.list_examples(dataset_name=...)`, `client.create_examples(dataset_name=..., examples=[{"inputs", "outputs", "metadata": {"item_id", "kind"}, "split": [...]}])`, `client.update_example(example_id, inputs=, outputs=, metadata=, split=)`, `client.delete_example`. The run uses `langsmith.evaluate(target, data=client.list_examples(dataset_name=name, splits=[split]), evaluators=[subject_detection], experiment_prefix=f"subject-detection-{split}", metadata={"split": split, "detect_threshold": ..., "detect_margin": ..., "multi_margin": ...}, max_concurrency=4, client=client)`, then collects each row's `evaluation_results["results"]` (`EvaluationResult.key`, `.score`) into `summarize`.
- [ ] **Step 5: Commit** — "Run and gate the subject-detection eval in LangSmith".

### Task 6 (controller, not a subagent): corpus, dataset, run, tune

- [ ] Fill `manifest.yaml` with CC BY 4.0 arXiv papers (license checked via OAI-PMH), pinned versions, SHA-256, subjects, metadata; `python -m evals.seed_corpus.download`.
- [ ] Generate the dataset (`--seed 86`), read every item, fix or drop mislabeled ones by hand; commit.
- [ ] `python -m evals.tune_detection --split smoke` → choose values; set them in `local/localstack/init/ready.d/10-smart-tutor.sh`, `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py`, PRD §9.13 settings table (bump version and changes line; AGENTS.md PRD version); apply to the running LocalStack with `awslocal`/`aws --endpoint-url`.
- [ ] `uv run --env-file ../.env python -m evals.run --split smoke` meets the targets; record the values and the experiment link in the PR.
