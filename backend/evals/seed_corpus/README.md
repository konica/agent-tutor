# Seed corpus

The fixed, openly licensed documents every evaluation runs on (PRD §10.3). `manifest.yaml` is the source of truth: where each document comes from, its license and SHA-256, and its labels (subjects, metadata, work key, citation links).

- **PDFs are not committed.** `cd backend && uv run --extra eval --extra ingest python -m evals.corpus` fetches each entry into `data/seed_corpus/` (git-ignored) and checks its SHA-256.
- **Labels live in the manifest**, so datasets reference documents by `id` and stay stable across versions.
- **Adversarial PDFs** (PRD §10.3 step 5) are built from the base paper (`qlora-2023`) by `evals.adversarial_pdfs`, which plants the taxonomy's document seeds. They have source type `adversarial` and `injection_eval: true`, so the ask generator skips them. Learner 1 holds them, plus the control handout `control-prompt-injection-course` (generated, CC0), a benign course note that quotes attacks.
- **Canary documents** (`generated/`, `canary:` in the manifest): learner 2's generated notes; `evals.pdf` renders them the same bytes every time, so their SHA-256 is pinned like a download's. The injection eval fails when a canary string reaches learner 1.
- **Highlight fixture:** `../highlight_fixture.py` chunks the first pages as the worker does; with the pdf.js text layer they form `web/src/features/viewer/fixtures/seed-text.json`, which checks the viewer's citation highlight (commands in that folder's README).
- **Gold-evidence papers:** `wikiskill-2026` and `jevharness-2026` are in learner 2's library; the gold rows of the ask dataset quote them (`../README.md`, "Gold rows"). `jevharness-2026` is CC BY-NC-SA 4.0, so use short, attributed excerpts only.
- **Synthetic learners** for dedupe and isolation tests are listed in `learners.yaml`: each holds a subset of the corpus. `uv run --extra eval --extra ingest python -m evals.learners` loads their libraries (`../README.md`, "Eval learners").

Only add documents whose license allows redistribution of excerpts (e.g. CC-BY); record the license as an SPDX id.
