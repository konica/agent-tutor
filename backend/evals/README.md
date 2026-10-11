# evals

Datasets live in **LangSmith** (versioned there; never edit a version a release was gated on). This folder holds what builds and runs them (PRD §10).

| Path | What |
|---|---|
| `seed_corpus/` | Manifest of the openly licensed documents every eval uses, with labels (PDFs downloaded to `data/seed_corpus/`, not committed) |
| `seed_corpus/learners.yaml` | The two eval learners and the seed documents in each library |
| `corpus.py` | Downloads the seed PDFs into `data/seed_corpus/` and checks each against the manifest's SHA-256 |
| `learners.py` | Loads the eval learners' libraries through the upload path (see "Eval learners") |
| `generators/` | Synthetic Q&A from the corpus, off-topic and near-scope negatives, (R2) learning-loop fixtures |
| `adversarial/taxonomy.yaml` | Injection categories × seeds |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `highlight_fixture.py` | The worker's chunks of seed-corpus PDFs for the viewer's highlight test: `uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out ../data/highlight-chunks.json ../data/seed_corpus/*.pdf` (then `web/src/features/viewer/fixtures/README.md`) |
| `run.py` | `make evals-smoke` → one LangSmith experiment per dataset, gated on `thresholds.yaml` (see "Run a split") |
| `gate.py` | Compares scores with `thresholds.yaml`: min, max, max_failures; unscored metrics are "not run" |
| `suite.py` | A suite: dataset + target + evaluators; discovered in `evaluators/` |
| `dataset.py`, `datasets/` | Hand-written datasets, one YAML per LangSmith dataset, pushed once per split version |

Splits: **smoke** (every PR that changes the agent; about 10 hand-written questions today, growing to ~30 as suites are added) and **full** (before release).

## Eval learners

Every eval asks as one of two synthetic learners whose libraries are built from the seed corpus. `seed_corpus/learners.yaml` says which documents each holds; learner 2 holds documents learner 1 must never see. Load both libraries with

    cd backend && uv run --extra eval python -m evals.learners     # or: make evals-learners

It downloads the seed PDFs into `data/seed_corpus/` (checked against the manifest's SHA-256), signs in as `learner@example.com` and `learner2@example.com`, uploads each document through the real upload path, chooses its labeled subjects, and waits until it is ready. It exits 1 when a document fails or doesn't get ready within `--timeout` seconds per learner (default 900). A second run uploads nothing for documents already in the library; an archived document is uploaded once more, which finds it, and is then restored; a document an earlier run left failed is retried once when it can be. A run interrupted between starting an upload and storing the file can leave a "processing" entry in the learner's Library; delete it there.

Prerequisites:
- The Compose stack with the app profile (`docker compose --profile app up -d`), or the dependencies plus host processes (`make api`, `make worker`; README "Run the app").
- Your AWS profile (`AWS_PROFILE` in `.env`, logged in): the worker describes and embeds each PDF with Bedrock in us-east-1.
- Internet access to arxiv.org for the first download.

## Run a split

    make evals-smoke     # or: cd backend && uv run --env-file ../.env --extra eval python -m evals.run --split smoke

It runs every suite whose dataset has the split, one LangSmith experiment per dataset, then prints each `release_1` metric of `thresholds.yaml` as PASS, FAIL, or "not run" (no suite scores it yet) with the experiment links, and exits 1 when a metric fails or nothing ran. `--release` picks another table.

Prerequisites: the app stack and the eval learners' libraries (`make evals-learners`, above); your AWS profile (the agent and the Qwen judge run on Bedrock); `LANGSMITH_API_KEY` in your shell or `.env`.

## Datasets

Each `datasets/<key>.yaml` is one LangSmith dataset (`name`), its examples grouped in splits. The first run of a split's `version` replaces that split's examples in LangSmith and tags the result with the version; later runs read the tagged version. A run refuses when the file no longer matches its version: to change a split, edit it **and** give it a new version (`smoke-v2`), so a version a run was gated on is never edited. Examples name seed documents by manifest id; the target finds each learner's own copy.

## Add a suite

1. Write `evaluators/<metric>.py`: evaluator functions taking any of `inputs`, `outputs`, `reference_outputs` and returning `{"key": "<thresholds.yaml metric>", "score": ..., "comment": ...}` (a nested metric is its dotted path, e.g. `decline_correctness.correctly_declined`), and a `SUITE = Suite(dataset=..., target=..., evaluators=(...))`. A judge's prompt goes in `evaluators/rubrics/`.
2. Add its examples as a split of `datasets/<dataset>.yaml` (a new split, or a new version of an existing one). A suite on a new dataset brings a target in `targets.py` that turns one example into the outputs its evaluators read.

The runner finds the suite; no change to `run.py`. Suites on the same dataset must name the same target and share one experiment.
