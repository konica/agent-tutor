# Seed corpus

The fixed, openly licensed documents every evaluation runs on (PRD §10.3). `manifest.yaml` is the source of truth: where each document comes from, its license and SHA-256, and its labels (subjects, metadata, work key, citation links).

- **PDFs are not committed.** `cd backend && uv run --extra eval python -m evals.corpus` fetches each entry into `data/seed_corpus/` (git-ignored) and checks its SHA-256.
- **Labels live in the manifest**, so datasets reference documents by `id` and stay stable across versions.
- **Adversarial PDFs** (PRD §10.3 step 5) are generated from seed documents with injected instructions and marked `adversarial: true`.
- **Highlight fixture:** `../highlight_fixture.py` chunks the first pages as the worker does; with the pdf.js text layer they form `web/src/features/viewer/fixtures/seed-text.json`, which checks the viewer's citation highlight (commands in that folder's README).
- **Synthetic learners** for dedupe and isolation tests are listed in `learners.yaml`: each holds a subset of the corpus. `uv run --extra eval python -m evals.learners` loads their libraries (`../README.md`, "Eval learners").

Only add documents whose license allows redistribution of excerpts (e.g. CC-BY); record the license as an SPDX id.
