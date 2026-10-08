# Eval datasets

`subject_detection.yaml` holds labeled first questions for the subject-detection eval (PRD §10.1). Each item gives a
learner (a set of seed-corpus document ids), the question, and the subject names detection should bind. `single` and
`multi` items are clear; `ambiguous` items straddle subjects, so asking is correct. Smoke items (`smoke: true`) form
the quick split.

The file is generated, not hand-written. Regenerate it (calls Bedrock for embeddings and the judge model; the seed PDFs
must be downloaded first, see `evals/seed_corpus/README.md`):

```bash
cd backend
uv run --env-file ../.env --extra eval python -m evals.seed_corpus.download
uv run --env-file ../.env --extra eval python -m evals.generators.subject_detection --seed 86
```

The same seed and corpus give the same learners, chunk picks, and ids; question text can differ between model runs.
Edits are reviewed in the PR like code. `load_items` rejects an item whose expected subjects are not all among its
learner's subjects, or whose learner has fewer than 2 subjects, because detection is skipped for those.
