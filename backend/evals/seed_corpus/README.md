# Seed corpus

The fixed, openly licensed documents every evaluation runs on (PRD §10.3). `manifest.yaml` is the source of truth: where each document comes from, its license and SHA-256, and its labels (subjects, metadata, work key, citation links).

- **PDFs are not committed.** From `backend/`, `uv run --extra eval python -m evals.seed_corpus.download` fetches each entry into `data/seed_corpus/` (git-ignored), checks its SHA-256, and fails without writing the file on a mismatch. Files already present and matching are skipped; arXiv fetches are paced 3 s apart.
- **Labels live in the manifest**, so datasets reference documents by `id` and stay stable across versions.
- **Adversarial PDFs** (PRD §10.3 step 5) are generated from seed documents with injected instructions and marked `adversarial: true`.
- **Synthetic learners** for detection, growth, dedupe, and isolation tests are built from subsets of the corpus by `../generators/`.

Only add documents whose license allows redistribution of excerpts (e.g. CC-BY); record the license as an SPDX id.
