# 0011. Per-learner contents: no cross-user deduplication; owners can delete

- Status: accepted
- Date: 2026-10-08
- Supersedes: the cross-user parts of 0002

## Context

ADR 0002 stored each unique file once in the whole system. A learner whose upload matched another learner's file got a document linked to the shared content, with no re-extraction or re-embedding. End-user feedback (PRD v2.22, Q54) rejected this as hidden sharing. The link also had concrete costs:

- **Timing signal.** A duplicate became ready in seconds, which revealed that another learner had the file.
- **Shared state.** Failure and retry state were shared across learners.
- **Deletion blocked.** One learner's file couldn't be removed without touching another's library. The same feedback asked for owners to delete documents (Q57), and the new document viewer needs each PDF available (Q56, Q58).

Embedding is a small part of processing cost, so the saving from sharing contents is small.

## Decision

- **Content stays separate from document**, but a content has **one owner**:
  - it is unique per `(owner_id, sha256)` and stored at `contents/<owner_id>/<content_id>.pdf`, with its page text next to it (keyed by `content_id`, so a delete and a re-upload of the same file never share an S3 key);
  - the worker's insert-or-get uses `(owner_id, sha256)` and never looks up another learner's content.
- **Duplicates only within a learner's library:**
  - the browser hash skips an upload of a file the learner already has;
  - the server hash catches what the browser missed, and the learner is pointed to the existing document;
  - `added_via` loses `dedupe`.
- **`can_read(user, document)`** is unchanged. Release 4 sharing gives grantees read access to the owner's content through grants, never by matching a hash.
- **Delete:**
  - the owner can delete a document that isn't processing or shared;
  - this removes the document, its content, its chunks, and every S3 version of the PDF and page text;
  - `thread_documents` rows keep the display title, so conversations show the document as deleted;
  - citations to removed chunks resolve to "Deleted document".
- **No Glacier tier.** PDFs stay in S3 Standard while their document exists, and the Glacier tagger job and lifecycle rule are dropped.

## Consequences

- **More embedding.** A file several learners upload is processed and embedded once per learner, and dedupe-ratio metrics go away.
- **Simpler isolation.** No row is shared between learners, so isolation tests also cover "same file, two learners" and delete affects only its owner.
- **Migration.** Existing shared contents with documents from several owners are split: each extra owner gets a copy of the content, chunks, and S3 objects (or the content is re-processed). In the pilot's data this is rare.
- **Release 2 work links** are computed per content. A learner's research map uses only links whose evidence is in a content they can read.
