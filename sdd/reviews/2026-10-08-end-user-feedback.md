# End-user feedback, 2026-10-08: per-learner uploads, conversations without subjects, documents used, delete

- Date: 2026-10-08
- Decided by: product owner (Thao Dinh)
- Result: PRD v2.21 (Q54–Q58), ADR 0011, design brief v0.8

## Feedback

1. The same document should be uploadable by different learners as their own copy. The system should not link a learner's upload to a copy someone else uploaded ("auto-sharing").
2. A learner should be able to chat without a subject. Detecting which subject a question is about is a nice-to-have and must never stop the learner from chatting.
3. A conversation should keep the list of documents used during the chat. The learner sees the list and opens a document to read it.
4. The learner should see where a cited chunk is in its document: the system opens the document and scrolls to that position.
5. An owner can delete their own documents, as long as the documents aren't shared with anyone.

## What the product did before (PRD v2.20)

- **D18:** a file whose SHA-256 matched any existing content was linked to it ("auto-shared"): the second learner got their own library entry, but the stored PDF, text, chunks, embeddings, and processing state were shared. Access stayed owner-only.
- **D3, US-3, US-3b:** every conversation was bound to 1–3 subjects, detected from the first question or picked by the learner when detection was unsure. It grew to at most 3 and offered "New conversation" for a fourth.
- **D10:** documents were never deleted, only archived; unreferenced PDFs moved to Glacier.

The cross-user link also had costs beyond how it felt to learners:
- **Timing signal:** a duplicate reached *choose subjects* in about 10 s, which told the learner that someone else already had the file.
- **Shared state:** a failed content failed for everyone, and any linked learner's Retry spent the shared attempts.
- **Deletion blocked:** one learner's content couldn't be removed without affecting another.

## Decisions

| # | Question | Decision |
|---|---|---|
| Q54 | The same file from different learners | **Per learner.** Contents are unique per `(owner, SHA-256)`. Duplicates are caught only within the learner's own library (browser check before upload, server hash after it). Two learners with the same file have two contents, processed and embedded separately. ADR 0011. |
| Q55 | Subjects in conversations | **Removed.** No subject detection, no subject choice, no 3-subject limit, no "New conversation". Every turn searches all of the learner's ready, non-archived documents. Documents keep their 1–3 subjects for organizing the library; conversations and notes take subjects from their documents used, for filtering. |
| Q56 | Documents of a conversation | The conversation keeps its **documents used** (documents whose chunks were given to the model for an answered turn). The learner opens one in the **document viewer** (the PDF); a citation opens at its page with the chunk text highlighted. |
| Q57 | Deleting a document | The owner can delete a document unless it is processing or (Release 4) shared. The PDF, page text, chunks, and embeddings are removed. Conversations and notes keep their text; citations read "Deleted document" with no link; the documents-used list highlights it as "Deleted" and it can't be opened. Archive stays the reversible option. |
| Q58 | Glacier | Removed: PDFs stay in S3 Standard while their document exists, so the viewer can open them. |

## Defaults chosen (no further question needed)

- "Documents used" means the documents whose chunks were given to the model for an answered turn. A decline adds none.
- Archived documents open in the viewer read-only. Deleted documents can't be opened.
- When a chunk's text can't be found on its page, the viewer opens the page without a highlight.
- A conversation's or note's subjects, for filtering, are the subjects of its documents used.
- Chunks gain `start_index`, their character offset in the page's cleaned text. Existing chunks are backfilled by re-chunking the saved page text.
- Delete removes every S3 version of the PDF. Traces that contain the document's text expire with the 180-day trace retention.

## Product owner and UI/UX review (2026-10-08)

Both reviews read PRD v2.21 and brief v0.8. Their questions all had simple defaults consistent with the owner's decisions, so the defaults were adopted (PRD Q59); the owner can override any of them in the PR review.

| Topic | Default adopted |
|---|---|
| Subject filter for conversations and notes | One rule, at read time: subjects of the thread's documents used that still exist (archived included, deleted excluded). Notes no longer store subjects; learning records keep a snapshot. |
| Excerpts after delete | Retrieved chunk text is not kept in the thread's saved state; citations are stored as `(document_id, chunk_id, page)`. A delete leaves the learner's and tutor's messages and removes nothing else from the conversation. |
| When a turn counts | Only when its answer is saved. A stopped answer or lost stream adds nothing. A delete during a streamed answer: the answer is saved, the document shows as "Deleted". |
| Which documents open in the viewer | Ready, *choose subjects*, and archived (read-only). Not processing or failed. The viewer renews its short-lived link while open. Restore from the viewer keeps it open. |
| Highlight matching | pdf.js text layer matched against the chunk text after the chunking cleanup; `start_index` picks between repeats; no match → page without highlight. Seed-corpus target ≥ 95% plus a content-free production count of misses. |
| Storage keys and re-upload | `contents/<owner_id>/<content_id>.pdf`: a delete and a re-upload of the same file never share a key; old citations never point to the new upload. |
| Migration | A shared content is copied for each extra owner (row, chunks, S3 objects, state); afterwards every content has one owner. |
| Storage growth | Accepted at pilot scale; storage per learner reported next to the budget alerts. |
| Documents used in chat | Header button "Documents used (*N*)" opening a side panel; the viewer replaces the panel and Close returns to it. |
| Viewer | Modal overlay (~720 px) over the dimmed screen; Close returns focus to the opener; keyboard paging; announced highlight. |
| Delete dialog | Cancel focused; danger-styled "Delete"; "Archive instead" as a secondary action; same dialog from details. |
| Deleted treatment | Muted but readable title, "Deleted" badge with icon and text, no strikethrough; not interactive. |

New states from the review: `viewer-loading`, `viewer-error`, `chat-documents-used-empty`, `library-more-menu`; `chat-new-conversation` merges into `chat-new`.

## Effect on tickets

- **Close as not planned** (detection work): #12 US-3b, #85, #86, #113.
- **Re-scope:** #11 becomes "US-3 Start a conversation". #13 US-4, #14 US-5, #19 US-10, #21 US-11, #22 US-12, and #23 US-13 follow PRD v2.21.
- **Undo built behavior:**
  - #83 and #84 bound threads to subjects; a new slice removes thread subjects and detection from the agent, the API, and the web.
  - #60 links duplicates across learners; a new slice under US-11 makes contents per learner.
- **New slices:**
  - documents used in a conversation (US-4b);
  - document viewer at a cited chunk (US-4b);
  - delete a document (US-10c).
- **Design:** brief v0.8 lists the states to add or remove. The tickets cite the v0.7 states that still apply until round v0.8 is accepted.
