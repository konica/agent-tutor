# evals

Datasets live in **LangSmith** (versioned there; never edit a version a release was gated on). This folder holds what builds and runs them (PRD §10).

| Path | What |
|---|---|
| `seed_corpus/` | Manifest of the openly licensed documents every eval uses, with labels (PDFs downloaded to `data/seed_corpus/`, not committed) |
| `generators/` | Synthetic Q&A from the corpus, off-topic and near-scope negatives, detection/ambiguous items, multi-turn subject switches, (R2) learning-loop fixtures |
| `adversarial/taxonomy.yaml` | Injection categories × seeds |
| `evaluators/` | One module per PRD §10.1 evaluator; `rubrics/` holds the Qwen judge prompts |
| `targets.py` | How an evaluation run invokes the agent |
| `thresholds.yaml` | Release-gate targets |
| `run.py` | `uv run --extra eval python -m evals.run --split smoke` → LangSmith experiment |

## Subject detection

The dataset is YAML in the repo (`datasets/subject_detection.yaml`); LangSmith holds a synced, versioned copy. Each run adds, updates, and deletes examples there (matched by `metadata.item_id`) so the two agree.

| Command | What |
|---|---|
| `make seed-corpus` | Download the seed PDFs to `data/seed_corpus/`, checking each SHA-256 |
| `make evals-smoke` / `python -m evals.run --split full` | Sync the dataset, run the split as a LangSmith experiment, print the scores against `thresholds.yaml` and the experiment link; exit 1 when a target is missed. Uses the policy in SSM (what the agent would load); `--policy T,M,MM` overrides it |
| `make evals-tune-detection` | Embed each question once, sweep (threshold, margin, multi-margin) offline, print the 10 policies with the most slack and the current SSM policy's metrics. No LangSmith |

Tuning workflow: run `make evals-tune-detection`, pick a policy, try it with `python -m evals.run --split full --policy T,M,MM`, then set the three SSM parameters and rerun without `--policy` to confirm the gate. The first run embeds the corpus (Bedrock) and caches the index under `data/seed_corpus/index/`.

Splits: **smoke** (~30 items, every PR) and **full** (before release).
