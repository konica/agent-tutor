# Smart Tutor

An AI tutor that answers a learner's questions only from the learner's own documents, with citations. Seeded from `sdd/prd.md` §4; the PRD wins if the two disagree.

## Library

**Content**:
One unique file, identified by the SHA-256 of its bytes. Processed and embedded once in the whole system, however many learners hold it.
_Avoid_: File, upload, blob

**Work**:
The paper or book a content represents. Different files of the same paper (preprint, published version) are different contents of one work.
_Avoid_: Paper, publication

**Document**:
A learner's library entry for a content, with its owner, 1–3 subjects, state, and archived flag. Never deleted, only archived.
_Avoid_: File, upload, PDF (when meaning the library entry)

**Library**:
All documents a learner owns.
_Avoid_: Collection, shelf

**Chunk**:
An embedded fragment of a content, with its page, used for search and citation. Belongs to the content, not to a learner.
_Avoid_: Passage, segment

**Visibility**:
Who may read a document: `private` (owner only) in Releases 1–3; `shared` and `public` from Release 4.

## Subjects

**Subject**:
An entry in the shared subject catalog, identified by a `subject_id` that never changes. Created when a learner names a new subject; reused by everyone.
_Avoid_: Topic, category, tag

**Subject name**:
What a learner sees for a subject: their personal name if they renamed it, otherwise the canonical name.
_Avoid_: Label, title

**My subjects**:
The subjects of a learner's ready, non-archived documents. Detection and search work only within these.

## Tutoring

**Thread**:
One conversation. Starts with the subjects detected from its first question, or picked by the learner when detection is unsure, and grows to at most 3 subjects; subjects are never removed.
_Avoid_: Chat, session, conversation (in code; "conversation" is fine in UI copy)

**Citation**:
The reference returned with an answer: the document's display title and page, or "page unavailable".
_Avoid_: Source, reference

**Decline**:
The tutor's refusal to answer a question its documents do not support or that matches none of the learner's subjects.
_Avoid_: Refusal, rejection

**Decline log**:
Anonymized record of declined questions, with no user id, kept 90 days.

## Learning

**Lesson Note**:
A learner-owned Markdown summary of one thread. One note per thread; deleting it archives it.
_Avoid_: Summary, notes

**Learning record**:
A lifetime entry describing what was learned in a thread (subjects, topics, key points). At most one per thread, written on "Summarize lesson" or after the thread goes idle.
_Avoid_: Memory, history

## Later releases

**Research map** *(R2)*:
Per subject, the learner's works on a timeline with citation links and a suggested reading order.

**Topic catalog** *(R3)*:
The topics each content covers, taken from its headings.

**Quiz** / **Report** *(R3)*:
Multiple-choice questions from Lesson Notes, graded in code; daily and weekly summaries with recommendations.

**Knowledge graph** *(R5)*:
Model-labeled relationships between works, with evidence.
