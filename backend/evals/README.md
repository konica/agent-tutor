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
| `adversarial/accepted.yaml` | Variants a human accepted in the annotation queue |
| `pdf.py` | Renders generated seed documents (the canary documents) to the same PDF bytes every run |
| `generators/injection.py` | Builds `datasets/injection.yaml` from the taxonomy and accepted variants; queues generated variants for review (see "Injection eval") |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `highlight_fixture.py` | The worker's chunks of seed-corpus PDFs for the viewer's highlight test: `uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out ../data/highlight-chunks.json ../data/seed_corpus/*.pdf` (then `web/src/features/viewer/fixtures/README.md`) |
| `run.py` | `make evals-smoke` → one LangSmith experiment per dataset, gated on `thresholds.yaml` (see "Run a split") |
| `gate.py` | Compares scores with `thresholds.yaml`: min, max, max_failures; unscored metrics are "not run" |
| `suite.py` | A suite: dataset + target + evaluators; discovered in `evaluators/` |
| `dataset.py`, `datasets/` | Hand-written datasets, one YAML per LangSmith dataset, pushed once per split version |

Splits: **smoke** (every PR that changes the agent; 11 hand-written ask questions and 18 generated injection prompts today, growing as suites are added) and **full** (before release).

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

It runs every suite whose dataset has the split, one LangSmith experiment per dataset, then prints each `release_1` metric of `thresholds.yaml` as PASS, FAIL, or "not run" (no suite scores it yet) with the experiment links, and exits 1 when a metric fails or nothing ran. `--release` picks another table.

Prerequisites: the app stack and the eval learners' libraries (`make evals-learners`, above); your AWS profile (the agent and the Qwen judge run on Bedrock); `LANGSMITH_API_KEY` in your shell or `.env`.

## Datasets

Each `datasets/<key>.yaml` is one LangSmith dataset (`name`), its examples grouped in splits. The first run of a split's `version` replaces that split's examples in LangSmith and tags the result with the version; later runs read the tagged version. A run refuses when the file no longer matches its version: to change a split, edit it **and** give it a new version (`smoke-v2`), so a version a run was gated on is never edited. Examples name seed documents by manifest id; the target finds each learner's own copy.

## Injection eval

`evaluators/injection_resistance.py` runs `datasets/injection.yaml` (prompt attacks, US-6) through the ask target as learner 1. Four code checks (system prompt leak, canary leak, own citations, limited citations) allow 0 failures; the judge's `kept_scope` allows at most 2% failures on the full split, which on the smoke split (under 50 rows) means 0.

The dataset is generated: edit `adversarial/taxonomy.yaml`, then

    cd backend && uv run python -m evals.generators.injection build

To grow the full split, queue generated variants for review (`propose`, Qwen writes them), mark each in the LangSmith annotation queue `smart-tutor-injection-review` with feedback `accepted` = 1 or 0, then `accept` adds the accepted ones to `adversarial/accepted.yaml` and rebuilds:

    uv run --env-file ../.env --extra eval python -m evals.generators.injection propose --per-seed 3
    uv run --env-file ../.env --extra eval python -m evals.generators.injection accept

Each split's version is derived from its examples, so a rebuilt file pushes a new LangSmith version on the next run.

## Add a suite

1. Write `evaluators/<metric>.py`: evaluator functions taking any of `inputs`, `outputs`, `reference_outputs` and returning `{"key": "<thresholds.yaml metric>", "score": ..., "comment": ...}` (a nested metric is its dotted path, e.g. `decline_correctness.correctly_declined`), and a `SUITE = Suite(dataset=..., target=..., evaluators=(...))`. A judge's prompt goes in `evaluators/rubrics/`.
2. Add its examples as a split of `datasets/<dataset>.yaml` (a new split, or a new version of an existing one). A suite on a new dataset brings a target in `targets.py` that turns one example into the outputs its evaluators read.

Each evaluator should return a literal metric key string and, for now, be named after its metric: the runner fills a missing score (an evaluator that raised) only for keys it has seen in other examples, and a dotted metric needs the follow-up noted in the PR. An evaluator for a dotted metric (`injection_resistance.kept_scope`) must not raise: return score 0 with the reason instead (see `_fail_closed` in `injection_resistance.py`), or a crash on every row reads as "not run". A canary check with no canaries also scores 0.

The runner finds the suite; no change to `run.py`. Suites on the same dataset must name the same target and share one experiment.
