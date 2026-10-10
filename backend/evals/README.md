# evals

Datasets live in **LangSmith** (versioned there; never edit a version a release was gated on). This folder holds what builds and runs them (PRD §10).

| Path | What |
|---|---|
| `seed_corpus/` | Manifest of the openly licensed documents every eval uses, with labels (PDFs downloaded to `data/seed_corpus/`, not committed) |
| `generators/` | Synthetic Q&A from the corpus, off-topic and near-scope negatives, (R2) learning-loop fixtures |
| `adversarial/taxonomy.yaml` | Injection categories × seeds |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `highlight_fixture.py` | The worker's chunks of seed-corpus PDFs for the viewer's highlight test: `uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out ../data/highlight-chunks.json ../data/seed_corpus/*.pdf` (then `web/src/features/viewer/fixtures/README.md`) |
| `run.py` | `uv run --extra eval python -m evals.run --split smoke` → LangSmith experiment |

Splits: **smoke** (~30 items, every PR) and **full** (before release).
