# 0003. Shared subject catalog with stable ids and personal names

- Status: accepted
- Date: 2026-10-03

## Context

Learners organize uploads by subject without an admin-curated list. Suggestions, the research map, and later sharing work better with common names. Learners also want their own wording, and research topics overlap.

## Decision

- One shared catalog: each subject has a stable `subject_id` (UUID) and a canonical name. New names join the catalog immediately after normalization, reuse of a near-duplicate, and a personal-data/offensive check.
- Learners rename subjects **for themselves** (`user_subject_names`); the id never changes. There is no admin rename, merge, or hide.
- Every other table stores only `subject_id`s; names are resolved at read time.
- Documents have 1–3 subjects; threads start with 1–3 detected subjects and grow to at most 3.

## Consequences

- Renames never touch documents, threads, notes, or records.
- Without merge, near-duplicates created at the same moment remain separate (accepted as rare).
- Subject names are visible to all users; the name check is the only safeguard (accepted residual risk).
