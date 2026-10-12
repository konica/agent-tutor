# Smart Tutor

An AI tutor that answers a learner's questions only from the learner's own documents, with citations. Seeded from `sdd/prd.md` §4; the PRD wins if the two disagree.

## Library

**Content**:
One learner's copy of a file, identified by the SHA-256 of its bytes within that learner's library. Processed and embedded for that learner; two learners with the same file have two contents, never linked.
_Avoid_: File, upload, blob

**Work**:
The paper or book a content represents. Different files of the same paper (preprint, published version) are different contents of one work.
_Avoid_: Paper, publication

**Document**:
A learner's library entry for a content, with its owner, 1–3 subjects, state, and archived flag. Archived (restorable) or deleted by its owner when not shared.
_Avoid_: File, upload, PDF (when meaning the library entry)

**Library**:
All documents a learner owns.
_Avoid_: Collection, shelf

**Chunk**:
An embedded fragment of a content, with its page and its offset in the page text, used for search, citation, and the viewer's highlight.
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
The subjects of a learner's ready, non-archived documents. They organize and filter the library, conversations, and notes; search doesn't use them.

## Tutoring

**Thread**:
One conversation. Has no subjects; answers from all of the learner's ready, non-archived documents and keeps its **documents used**.
_Avoid_: Chat, session, conversation (in code; "conversation" is fine in UI copy)

**Turn**:
One question and its answer (or decline) in a thread, kept when the answer ends with `done`. A thread's turns, oldest first, are its history; a reopened conversation shows them.

**Rating**:
A learner's 👍/👎 (Helpful / Not helpful) on a kept turn: one per turn, a new one replaces it. Saved with the turn; #290 sends it to Phoenix as a `learner_rating` span annotation; 👎 extends the trace's retention.
_Avoid_: Vote, like, review

**Documents used**:
The documents whose chunks were given to the model for a conversation's answered turns, in order of first use. A deleted one stays listed as "Deleted" and can't be opened.

**Document viewer**:
The in-app PDF viewer; from a citation it opens at the chunk's page and highlights its text.

**Citation**:
The reference returned with an answer: the document's display title and page, or "page unavailable".
_Avoid_: Source, reference

**Decline**:
The tutor's refusal to answer a question the learner's documents do not support.
_Avoid_: Refusal, rejection

**Decline log**:
Anonymized record of declined questions, with no user id, kept 90 days.

**Learner hash**:
A keyed hash (HMAC-SHA256) of a learner's user id, the only way traces name a learner. Stable per learner, different between learners, and changes with the key.
_Avoid_: User id (in traces), pseudonym

## Learning

**Lesson Note**:
A learner-owned Markdown summary of one thread. One note per thread; deleting it archives it.
_Avoid_: Summary, notes

**Learning record**:
A lifetime entry describing what was learned in a thread (subjects, topics, key points). At most one per thread, written on "Summarize lesson" or after the thread goes idle.
_Avoid_: Memory, history

## Deployment

**Deployment mode**:
How one installation of Smart Tutor is hosted: **on-premise** (the default) or **native-cloud** (opt-in). The product behaves the same in both. Each mode has its own copy of every cloud resource it uses, image registry included; they share only the account's one-time setup.
_Avoid_: Environment, flavor, target

**On-premise mode**:
Smart Tutor's own services (web, API, agent, MCP server, worker, sign-in) run on a virtual machine we operate instead of managed Kubernetes. File storage, the ingest queue, settings, and its own image registry stay on the cloud provider's managed services; the model provider and the tracing service are external. It is the default and is deployed on every merge to `main` while `PRODUCTION_DEPLOY` is `true`, unless `ON_PREMISE_AUTO_DEPLOY` is `false`.
_Avoid_: Self-host, local, EC2 mode

**Native-cloud mode**:
Smart Tutor on the cloud provider's managed services end to end (managed Kubernetes, database, file storage, queue, CDN). Deployed only when explicitly chosen.
_Avoid_: AWS mode, pilot, production

## Later releases

**Research map** *(R2)*:
Per subject, the learner's works on a timeline with citation links and a suggested reading order.

**Topic catalog** *(R3)*:
The topics each content covers, taken from its headings.

**Quiz** / **Report** *(R3)*:
Multiple-choice questions from Lesson Notes, graded in code; daily and weekly summaries with recommendations.

**Knowledge graph** *(R5)*:
Model-labeled relationships between works, with evidence.
