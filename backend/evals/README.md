# evals

Datasets live in **LangSmith** (versioned there; never edit a version a release was gated on). This folder holds what builds and runs them (PRD §10).

| Path | What |
|---|---|
| `generators/` | Synthetic Q&A from the corpus, off-topic and near-scope negatives, detection/ambiguous items, multi-turn subject switches, (R2) learning-loop fixtures |
| `adversarial/taxonomy.yaml` | Injection categories × seeds |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `run.py` | `uv run --extra eval python -m evals.run --split smoke` → LangSmith experiment |

Splits: **smoke** (~30 items, every PR) and **full** (before release).
