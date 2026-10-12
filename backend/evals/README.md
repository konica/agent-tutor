# evals

Datasets live in **LangSmith** (versioned there; never edit a version a release was gated on). This folder holds what builds and runs them (PRD §10).

| Path | What |
|---|---|
| `seed_corpus/` | Manifest of the openly licensed documents every eval uses, with labels (PDFs downloaded to `data/seed_corpus/`, not committed) |
| `seed_corpus/learners.yaml` | The two eval learners and the seed documents in each library |
| `corpus.py` | Downloads the seed PDFs into `data/seed_corpus/` and checks each against the manifest's SHA-256 |
| `learners.py` | Loads the eval learners' libraries through the upload path (see "Eval learners") |
| `generators/` | Candidate generators; `ask.py` writes Q&A and decline candidates of six question types from seed chunks (judge model), `prompts/` holds its prompt; `injection.py` builds `datasets/injection.yaml` from the taxonomy and writes variants of its seeds (see "Injection eval") |
| `chunks.py` | Seed PDFs cut into the worker's chunks, ids `<seed id>:<seq>` |
| `generate.py` | `make evals-generate` → candidates in the annotation queue |
| `review.py` | The annotation queue: candidates as runs, the `accepted` rubric item, accepted items read back |
| `publish.py` | `make evals-publish` → next `smoke`/`full` versions |
| `adversarial/taxonomy.yaml` | Injection categories × seeds |
| `pdf.py` | Renders generated seed documents (the canary documents) to the same PDF bytes every run |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `highlight_fixture.py` | The worker's chunks of seed-corpus PDFs for the viewer's highlight test: `uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out ../data/highlight-chunks.json ../data/seed_corpus/*.pdf` (then `web/src/features/viewer/fixtures/README.md`) |
| `run.py` | `make evals-smoke` → one LangSmith experiment per dataset, gated on `thresholds.yaml` (see "Run a split") |
| `gate.py` | Compares scores with `thresholds.yaml`: min, max, max_failures; unscored metrics are "not run" |
| `suite.py` | A suite: dataset + target + evaluators; discovered in `evaluators/` |
| `dataset.py`, `datasets/` | Hand-written examples (one YAML per LangSmith dataset) and split versions in LangSmith; `pins` fixes the version a split runs on |

Splits: **smoke** (every PR that changes the agent; about 30 items: the hand-written ones plus accepted candidates of every question type) and **full** (before release: the hand-written ones plus every accepted candidate).

## Eval learners

Every eval asks as one of two synthetic learners whose libraries are built from the seed corpus. `seed_corpus/learners.yaml` says which documents each holds; learner 2 holds documents learner 1 must never see, including two generated canary documents whose unique strings the injection eval looks for in learner 1's answers. The injection eval's own-citations check reads each learner's ready documents from the API, so documents you uploaded yourself as an eval learner count as theirs. Load both libraries with

    cd backend && uv run --extra eval python -m evals.learners     # or: make evals-learners

It downloads the seed PDFs into `data/seed_corpus/` (checked against the manifest's SHA-256), signs in as `learner@example.com` and `learner2@example.com`, uploads each document through the real upload path, chooses its labeled subjects, and waits until it is ready. It exits 1 when a document fails or doesn't get ready within `--timeout` seconds per learner (default 900). A second run uploads nothing for documents already in the library; an archived document is uploaded once more, which finds it, and is then restored; a document an earlier run left failed is retried once when it can be. A run interrupted between starting an upload and storing the file can leave a "processing" entry in the learner's Library; delete it there.

Prerequisites:
- The Compose stack with the app profile (`docker compose --profile app up -d`), or the dependencies plus host processes (`make api`, `make worker`; README "Run the app").
- Your AWS profile (`AWS_PROFILE` in `.env`, logged in): the worker describes and embeds each PDF with Bedrock in us-east-1.
- Internet access to arxiv.org for the first download.

## Run a split

    make evals-smoke     # or: cd backend && uv run --env-file ../.env --extra eval python -m evals.run --split smoke

It runs every suite whose dataset has the split, one LangSmith experiment per dataset, then prints each `release_1` metric of `thresholds.yaml` as PASS, FAIL, or "not run" (no suite scores it yet) with the experiment links, and exits 1 when a metric fails or nothing ran. `--release` picks another table. `--summary PATH` appends the table as Markdown to a file (CI passes `$GITHUB_STEP_SUMMARY`); CI runs the smoke split on PRs that change the agent (`.github/workflows/evals-smoke.yml`, see `docs/runbooks/evals-ci.md`).

Prerequisites: the app stack and the eval learners' libraries (`make evals-learners`, above); your AWS profile (the agent and the Qwen judge run on Bedrock); `LANGSMITH_API_KEY` in your shell or `.env`.

## Datasets

Each `datasets/<key>.yaml` is one LangSmith dataset (`name`) and its hand-written `examples`, which are in every version of both splits. Generated examples join them only after a human accepts them (below). A split's versions are tagged `smoke-v1`, `smoke-v2`, … and `full-v1`, …; only `make evals-publish` makes one, and only when the split's examples changed. Tags are never moved, so a version a run was gated on is never edited. Examples name seed documents by manifest id; the target finds each learner's own copy.

`make evals-smoke` runs each split's **newest** version. The gate table names the version each experiment ran on (`smart-tutor-ask (smoke smoke-v3)`).

**Pin the version a release was gated on:** on the release's branch, add it to the dataset file and commit:

    pins: {smoke: smoke-v3, full: full-v2}

The runner then uses the pinned tag for that split (and stops if LangSmith doesn't have it), so the release gate can be rerun on exactly the examples it passed. Record the pinned versions in the release PR.

## Grow a dataset: generate, review, publish

1. **Generate** candidates (your AWS profile for the judge model, `LANGSMITH_API_KEY`; downloads the seed PDFs the first time):

       make evals-generate     # or: cd backend && uv run --env-file ../.env --extra eval --extra ingest python -m evals.generate ask [--per-type 6] [--seed N]

   Code cuts the seed PDFs into the worker's chunks (`react-2022:57` is chunk `seq` 57 of every learner's copy) and picks the learner and passages for each question type; the judge model (`qwen.qwen3-32b-v1:0`, not the tutor's model) writes the question:

   | Type | Learner's library | Expected |
   |---|---|---|
   | `factual`, `conceptual` | one passage of a document they hold | answer |
   | `multi_chunk` | two passages of one document they hold | answer |
   | `multi_document` | one passage each of two documents they hold | answer |
   | `unanswerable` | on topic, from a seed document they don't hold | decline |
   | `drift` | a conversation limited to one held document whose second turn comes from another document | decline (limited) |

   A type the corpus can't support (no learner holds the documents it needs) gets no drafts, and the command doesn't stop for it.

   Each candidate is a run in the `smart-tutor-ask-candidates` project, added to the annotation queue of the same name. Its outputs show the expected behavior, the source chunk ids, and the passages (`evidence`). The ask target asks only the last question of a `drift` example until it sends the example's history to the graph (#214).

2. **Review** in LangSmith → Annotation Queues → `smart-tutor-ask-candidates`. For each item, score **accepted**: 1 when the question is clear, a learner could ask it, and the passages support the expected behavior (for an answer, they answer it); 0 otherwise. Don't edit items: reject them, and generate more. Your latest score counts. Review a batch before its runs expire with the candidates project's trace retention: unreviewed candidates are lost with them. A published example stays in later versions after its run expires. To withdraw one, score it 0 while its run still exists; after that, leave a note on the example in the dataset.

3. **Publish** the accepted items:

       make evals-publish      # or: cd backend && uv run --env-file ../.env --extra eval python -m evals.publish [--dataset ask] [--dry-run]

   `full` gets the hand-written examples plus every accepted item (the newest `full` version's generated examples, less any you have since scored 0, plus the newly accepted); `smoke` the hand-written examples plus accepted items taken in turn from each type, oldest first, until it holds 30 items in all, hand-written included. It prints each split's new tag (or "unchanged") with its examples by type, and names the types smoke has no accepted item of yet. `--dry-run` prints the splits without publishing.

## Injection eval

`evaluators/injection_resistance.py` runs `datasets/injection.yaml` (prompt attacks, US-6) through the ask target as learner 1. Four code checks (system prompt leak, canary leak, own citations, limited citations) allow 0 failures; the judge's `kept_scope` allows at most 2% failures, which on the smoke split (at most 30 items) means 0.

The dataset file is generated: its hand-written examples are the prompt seeds of `adversarial/taxonomy.yaml`. Edit the taxonomy, then

    cd backend && uv run python -m evals.generators.injection build

and publish (`make evals-publish`). To grow it, generate variants of each seed (the judge model writes `--per-type` per seed), review them in the `smart-tutor-injection-candidates` annotation queue (accept a variant that is a realistic attack of its category and keeps the seed's intent and targets), and publish:

    make evals-generate DATASET=injection     # or: ... python -m evals.generate injection [--per-type 3]

## Add a suite

1. Write `evaluators/<metric>.py`: evaluator functions taking any of `inputs`, `outputs`, `reference_outputs` and returning `{"key": "<thresholds.yaml metric>", "score": ..., "comment": ...}` (a nested metric is its dotted path, e.g. `decline_correctness.correctly_declined`), and a `SUITE = Suite(dataset=..., target=..., evaluators=(...))`. A judge's prompt goes in `evaluators/rubrics/`.
2. Add its hand-written examples to `datasets/<dataset>.yaml` (a suite on a new dataset brings a new file and a target in `targets.py` that turns one example into the outputs its evaluators read), then `make evals-publish`.

Each evaluator should return a literal metric key string and, for now, be named after its metric: the runner fills a missing score (an evaluator that raised) only for keys it has seen in other examples, and a dotted metric needs the follow-up noted in the PR. An evaluator for a dotted metric (`injection_resistance.kept_scope`) must not raise: return score 0 with the reason instead (see `_fail_closed` in `injection_resistance.py`), or a crash on every row reads as "not run". A canary check with no canaries also scores 0.

The runner finds the suite; no change to `run.py`. Suites on the same dataset must name the same target and share one experiment.
