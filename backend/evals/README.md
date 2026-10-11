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
| `run.py` | `uv run --extra eval python -m evals.run --split smoke` → LangSmith experiment |

Splits: **smoke** (~30 items, every PR) and **full** (before release).

## Eval learners

Every eval asks as one of two synthetic learners whose libraries are built from the seed corpus. `seed_corpus/learners.yaml` says which documents each holds; learner 2 holds documents learner 1 must never see. Load both libraries with

    cd backend && uv run --extra eval python -m evals.learners     # or: make evals-learners

It downloads the seed PDFs into `data/seed_corpus/` (checked against the manifest's SHA-256), signs in as `learner@example.com` and `learner2@example.com`, uploads each document through the real upload path, chooses its labeled subjects, and waits until it is ready. It exits 1 when a document fails or doesn't get ready within `--timeout` seconds per learner (default 900). A second run uploads nothing: the learner's own duplicate check finds each document; a document an earlier run left failed is retried once, an archived one is restored.

Prerequisites:
- The Compose stack with the app profile (`docker compose --profile app up -d`), or the dependencies plus host processes (`make api`, `make worker`; README "Run the app").
- Your AWS profile (`AWS_PROFILE` in `.env`, logged in): the worker describes and embeds each PDF with Bedrock in us-east-1.
- Internet access to arxiv.org for the first download.
