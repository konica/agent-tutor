# 0002. Separate contents from documents; deduplicate by SHA-256

- Status: accepted
- Date: 2026-10-03

## Context

Learners upload their own PDFs (PRD v2). Popular papers will be uploaded by many learners, and embedding is the main ingestion cost. Documents must stay private, and Release 4 adds sharing and publishing without re-uploading.

## Decision

- **Content** = one unique file, keyed by the SHA-256 of its bytes: stored once, extracted, chunked, and embedded once in the whole system. Holds metadata, references, work key, and saved Docling output. No owner.
- **Document** = a learner's library entry pointing to a content: owner, 1–3 subjects, state, archive flag, visibility. Unique per `(owner, content)`.
- A duplicate upload is linked to the existing content **only after the server hashes the uploaded bytes**. A browser-sent hash only skips re-uploading a file already in the learner's own library.
- One access rule, `can_read(user, document)`, used by the API, MCP search, and citations; Release 1 = owner only, Release 4 extends it with grants and public visibility.

## Consequences

- Embedding cost is paid once per unique file; a duplicate costs only the upload.
- Content state (processing, ready, failed) is shared, so a retry by one learner helps all linked learners.
- The same paper in different files (preprint vs published) is embedded twice; `work_key` groups them for the research map.
- Archiving is per document; a content PDF moves to Glacier only when no non-archived document references it.
