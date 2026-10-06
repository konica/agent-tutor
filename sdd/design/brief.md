# Smart Tutor — Design Brief

| | |
|---|---|
| **Brief version** | v0.6 |
| **Based on** | `sdd/prd.md` Draft v2.15 |
| **Status** | Draft, round 5 (landing page and stock Keycloak pages, merged with the scope cut: no terms of use step, no Settings page) |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-06 |
| **Designer** | Open Design |

> **For the designer:** this brief is the source of truth for the mockups. If the brief and the PRD disagree, follow the brief and flag the conflict. Name every deliverable with the brief version it answers (e.g. `chat-growth-notice@v0.3`). Read **§0 What changed** first on every new version. A ready-to-paste prompt for starting a round is in **Appendix A**.

---

## 0. What changed in this version

**Targeted update.** Keep the round 4 prototype (landing page, stock Keycloak pages, terms and Settings already removed) and change only what is below. PRD v2.15 joins two changes made in parallel as "v0.5": the landing page and stock Keycloak pages (Q46; `sdd/reviews/2026-10-06-landing-page-discussion.md`) and the removal of the terms of use step and the Settings page (Q45). This version answers the designer's G1–G4. The v0.4 and v0.5 changes are in the changelog (§13).

| Change | States |
|---|---|
| **New public landing page** at `/` (§6.0): what Smart Tutor does, the honesty points, "Create an account" and "Sign in". Text only, no product image. Signed-in visitors see the same page. **No "Terms of use" link in the footer.** | `landing-default` |
| **Keycloak pages are Keycloak's stock layout** (`keycloak.v2`) with only the Smart Tutor logo, colors, font, and display name (§6.2). Show them as low-detail references; don't design layouts Keycloak won't render. | `auth-sign-up`, `auth-sign-in`, `auth-verify-email` (reduced) |
| **No terms of use step and no Settings page.** Sign-up lands straight on the empty Library; the left navigation ends at Usage. GMT+7 still applies to limit times and "today" (D8); no screen shows it as a setting. | `terms-first-run`, `terms-accepted`, `settings-default` stay removed |
| **J1 starts on the landing page;** sign-out returns to it (§5, §6.1; G4). | J1 flow, user menu |
| **Upload-rights line (G2).** The Library's upload area says "Only upload documents you have the right to use." in the first-run drop zone and next to the page's drop zone and "Upload" button. A plain line: no checkbox, nothing to accept. | `library-empty`, `library-default` and every Library state that shows the drop zone |
| **Sample data fixes** from round 3 (E1, E2): the scanned file's reason, and no subject on a document still processing (§9). | none (sample data) |

---

## 1. Product in one paragraph

Smart Tutor is a study tool for **the learner's own documents**. A learner uploads PDFs (research papers, books, course notes) into a private **Library**. For each upload, Smart Tutor reads the first pages and suggests three subjects; the learner keeps one to three with a click. The learner then just asks questions: the tutor works out which of their subjects the question is about, answers **only from their documents**, and shows where each answer came from (document and page). If their documents don't cover a question, it says so instead of guessing. Conversations become **Lesson Notes** the learner can edit and revisit. Release 2 adds a **research map**: how the learner's papers cite each other, a timeline, and a suggested reading order.

## 2. Who we are designing for

| Persona | What they need from the UI |
|---|---|
| **Learner / researcher** (the only persona with screens) | Get papers in with no filing effort; trust each answer (see the source); stay focused; find past conversations, notes, and documents fast; later, understand how the papers connect. |
| Admin | **No screens.** Do not design admin pages. |

Typical learner: a graduate student or self-taught engineer with dozens to hundreds of PDFs on overlapping topics (e.g. LLMs, agents, retrieval). They are comfortable with tools like Zotero, Notion, and ChatGPT, and impatient with setup.

**Tone:** calm, precise, scholarly but friendly. Plain English. The tutor never sounds chatty or overconfident.

## 3. Design principles

1. **Library first.** Nothing works without documents. Every empty state leads to uploading, and the first-run journey ends with a first answer, not a settings page.
2. **Suggest, don't ask.** Subjects are pre-suggested; accepting them is one click. Typing is the exception.
3. **Show the system's work honestly.** Processing takes seconds to minutes; always show which state a document is in, what happens next, and whether the learner needs to act.
4. **Trust is visible.** Answers carry citations (document and page). The conversation's subjects are always on screen.
5. **Scope is visible and grows predictably.** When a conversation gains a subject, the learner sees it happen inline. At the maximum of 3 they are told, before it matters.
6. **Declines are helpful, not errors.** A decline explains why and offers the next step.
7. **Nothing is lost.** "Delete" is always **Archive**, and everything archived can be restored. Never show a permanent-delete action.
8. **Private by default, with one clear exception.** Documents, conversations, and notes are private. **Subject names are shared with everyone**; the UI says so wherever a learner types one.
9. **One management pattern everywhere.** Library, Conversations, and Notes (and later Quizzes and Reports) share one list layout: filters, Active / Archived tabs, row actions, empty states.

## 4. Scope

**In scope for this round:**
- Release 1 learner web app at full fidelity (§5, §6).
- Release 2 research map as low-fidelity wireframes (§7).
- Release 3 learning loop as low-fidelity wireframes (§8), only to check that navigation scales.

**Laptop screens only** (1280–1920 px wide). Phones and tablets are not supported.

**Out of scope (do not design):**
- Admin UI of any kind (subject moderation, account deletion, analytics).
- Sharing, publishing, public document browser, import by DOI/arXiv, team workspaces (Release 4). Do not add "Share" buttons.
- Relationship labels between papers and concept history (Release 5).
- Token credits, plans, billing, or upgrade prompts.
- Web search, notifications (email/push), languages other than English.
- Restricting a conversation to selected documents.
- Phone and tablet layouts; native mobile apps.
- Keycloak's login, registration, and email-verification pages beyond the **logo, colors, font, and display name** on Keycloak's stock layout (Keycloak hosts them).
- On the landing page: pricing, testimonials, customer logos, blog, later-release features, product screenshots, stock "AI" imagery, mobile promises.

## 5. Key journeys (design these as clickable flows)

Design the screens in §6, then link them into these four flows. They are how the mockups will be reviewed.

**J1 First run (most important).** Landing page → "Create an account" → sign up and verify email (Keycloak) → empty Library ("Upload your first document") → drop 3 PDFs → watch processing → choose subjects for each (accept suggestions) → "Ready" → "Ask a question" → first cited answer.

**J2 Everyday question.** Open app → Chat → ask → subjects detected → cited answer → follow-up that **adds a second subject** → "Summarize lesson" → open the note.

**J3 Conversation reaches its limit.** A conversation already covers 3 subjects → a question clearly about a fourth subject → the tutor doesn't answer and offers **"New conversation"** carrying the question over → the new conversation answers it.

**J4 Library upkeep.** Filter the Library by subject → open a document → change its subjects → fix its display title → archive it → find it under Archived → restore it. Include one **failed** document and its **Retry**.

## 6. Release 1 screens (full fidelity)

Each screen lists the PRD user stories it implements. **Text in quotes is required wording**; refine everything else freely.

### 6.0 Landing page — US-1
The public page at `/` for anyone not signed in (and the same page for signed-in visitors). It answers "what is this?" for someone who opens the pilot link from an invitation. It sits **outside the app shell**: no left navigation, no upload tray. One short page, same tokens and fonts as the app (light required, dark supported).

- **Header:** Smart Tutor logo and name on the left; a text link **"Sign in"** on the right.
- **Hero:** headline, sub-line, **"Create an account"** (primary) and **"Sign in"** (secondary), and the line "Pilot · laptop browsers only." Text only: no product image or illustration.
- **How it works:** three steps: upload your PDFs, ask a question, check the page it came from.
- **Trust points:** four short points: only your documents; private to you; title and page cited; a pilot for laptop browsers.
- **Closing:** the two buttons again; a plain footer (no terms of use link).
- "Create an account" opens Keycloak's registration page, "Sign in" its login page; both return to the Library. A signed-in visitor who chooses "Sign in" goes straight to the Library.
- Use the copy in §9 verbatim where it is quoted.

### 6.1 App shell
- Left navigation, in this order: **Library** (home), **Chat** (starts a new conversation), **Conversations**, **Notes**, **Subjects**, **Usage**.
- Reserve space for later items without showing them: **Research map** (R2, after Library), **Quizzes** and **Reports** (R3, after Notes).
- **Library** shows a count badge when documents need the learner's action (choose subjects, or failed).
- User menu: name, sign out. Signing out returns to the landing page (§6.0).
- A global, non-blocking **upload tray** (bottom right) shows uploads in progress on every screen, so the learner can keep working while files process.

### 6.2 Keycloak pages — US-1
- Keycloak's hosted login, registration, and email-verification pages keep **Keycloak's stock layout** (`keycloak.v2`), fields, and messages. We change only the logo, the accent and background colors, the font, and the display name "Smart Tutor". Show them as low-detail references (`auth-*` states); keep focus rings visible and contrast AA.
- After sign-up or first sign-in, land on the empty **Library**. There is no terms of use step (PRD Q45); the upload-rights line in the Library replaces its checkbox (§6.3).

### 6.3 Library — US-2, US-10, US-11
The home screen and the hub for documents.

**Layout:** page header with **"Upload"**, a drop zone (the whole page accepts dropped files), filter bar, Active / Archived tabs, document table. Next to the drop zone and "Upload": "Only upload documents you have the right to use." (G2; no checkbox).

**Table columns:** display title (with authors and year beneath), subjects (chips, by the learner's names), state, upload date. Row actions: one contextual button per row (**Choose subjects**, **Retry**, **Restore**, or **Open**), and the rest (change subjects, edit title, archive / restore) under **"More"** (D5).

**Filters:** subject (matches any of a document's subjects), date range, state; combinable; "Clear filters".

**States to design:**

| State | What the learner sees |
|---|---|
| **Empty (first run)** | Large drop zone: "Upload your first document". Explain in one line: PDFs up to 50 MB and 500 pages; documents stay private. Under it: "Only upload documents you have the right to use." |
| **Rejected before upload** | Not a PDF, or over 50 MB: the file is not uploaded; inline message on its row in the upload tray with the reason. |
| **Already in your library** | The browser recognized the file: nothing uploads. "Already in your library" with a link to the document, or **"Restore"** if it is archived. |
| **Uploading** | Progress bar per file in the upload tray. |
| **Processing** | State "Processing" with an indeterminate indicator, and the extracted title once the first pages are read. No "Choose subjects" yet (Q7). Hint: "You can choose subjects when processing finishes." |
| **Choose subjects** (needs action) | Processing has finished. Highlighted row and a call-to-action **"Choose subjects"**; opens the subject picker (§6.4). A banner at the top of the Library: "*N* documents need subjects". |
| **Ready** | State "Ready". The document is searchable. |
| **Failed** | State "Failed" with the reason in plain words (e.g. "This PDF has more than 500 pages", "We couldn't read this PDF", "No text layer (scanned PDFs are not supported yet)") and **"Retry"**. After 3 attempts: "This file could not be processed" and no Retry. |
| **Archived tab** | Archived documents with **"Restore"**; their subjects can still be changed (D7). One line explaining archived documents are not used for answers but old citations still work. |
| **No results** | Filters match nothing: "No documents match these filters" and "Clear filters". |
| **Rate limited** | Upload limit reached (20 per hour, 100 per day): message with the time uploads are available again, in GMT+7, e.g. "You can upload again at 11:40" (D8). |

**Timing the designer should reflect:** the title appears within about 30 seconds of upload; subjects can be chosen when processing finishes, up to 5 minutes later (15 minutes for very long documents). A duplicate of a file Smart Tutor has already processed is ready within about 10 seconds — show it as a normal, fast Processing state; never say another user has the file.

### 6.4 Choose subjects (picker) — US-2b
A dialog (or side panel) opened from a document that needs subjects (processing has finished, Q7), and reused for "Change subjects", including on archived documents (D7).

- Document header: display title, authors, year, and the two-sentence **summary** Smart Tutor extracted.
- **Three suggestion chips**, each selectable. Mark where each came from, subtly: "Your subject", "Shared subject", or "New".
- Pre-select the first suggestion so accepting is one click; the learner can change it.
- **"Add your own"** type-ahead that searches the shared catalog as they type; choosing an existing subject is preferred to creating one.
- Selection counter: **1–3 subjects**. "Save" is disabled at 0; further chips are disabled at 3.
- Helper text under the type-ahead: **"Subject names are visible to everyone. Don't include personal information."**
- Feedback for a typed name:
  - Near-duplicate: "We'll use the existing subject *Large Language Models*." (the learner's text is mapped, not rejected);
  - Rejected (personal data or offensive): "Please choose a different name." with the reason in one short line;
  - Over 60 characters: blocked with a counter.
- After saving: "Subjects saved. *Title* is ready to use." The document is Ready and searchable right away.
- **Multiple documents waiting:** let the learner step through them ("2 of 3", Next / Skip) without closing the dialog.

### 6.5 Document details — US-10
A side panel (drawer) opened from a Library row.

- Display title (editable inline; "Reset to extracted title"), authors, year, DOI (if any), file name, pages, upload date, state.
- Summary.
- Subjects (chips) with **"Change subjects"** (opens §6.4), also when archived (D7).
- Actions: **Archive** / **Restore**; **Retry** when failed.
- Note: there is **no download** and **no delete**.

### 6.6 Chat — US-3, US-3b, US-4, US-5, US-6, US-7, US-9, US-10
The core screen. Structure: thread header (title, subject chips, citations switch, "Summarize lesson", note link), message column, input, and a **status line** under the input.

| State | What the learner sees |
|---|---|
| **No documents yet** | Chat is replaced by an empty state asking the learner to upload a document first, with an **"Upload"** button. |
| **Documents still processing** | Normal chat, plus a quiet hint above the input: "*N* documents are still processing and can't be used yet." |
| **New conversation** | Input with placeholder ("Ask about your documents…") and the learner's subjects shown as context ("Your subjects: …"). **No subject picker.** *Proposal, not in the PRD:* up to 3 example questions; design a slot for them and mark it optional. |
| **Subjects detected** | After the first question, 1–3 **subject chips** appear in the header (learner's names). No "Change" action. |
| **Detection unsure** | Tutor message "Which subjects is this about?" with the learner's subjects as selectable chips (pick 1–3) and "Continue". The original question stays visible and is answered after the pick, without retyping. |
| **Streaming answer** | Text appears progressively; **Stop** button. |
| **Answer with citations** | Under each answer: citations as compact references, "*Display title*, p. 42" (or "page unavailable"). Clicking one opens the document details. A citation to an archived document shows an "Archived" badge. Outline thumb icons labelled **"Helpful"** / **"Not helpful"** with a visible pressed state on each answer; "Not helpful" opens an optional reason (D1). |
| **Citations switch** | "Show citations" switch in the header, **on by default**. Off hides the citations under every answer in view; answers are unchanged. Remembered for the learner across conversations. Show the thread both ways. |
| **Subject added** | An inline **system notice** between messages (not a chat bubble): "Added *Retrieval-Augmented Generation* to this conversation". The new chip appears in the header with a brief highlight. |
| **Maximum reached** | Inline notice when the third subject is added: "This conversation now covers 3 subjects, the maximum. For other topics, start a new conversation." |
| **Fourth subject refused** | The tutor doesn't answer: "This conversation already covers 3 subjects: *LLMs*, *AI Agents* and *Retrieval-Augmented Generation*. Your question is about *Reinforcement Learning*, so I haven't answered it here." (D3), then "A new conversation will answer it straight away." and **"New conversation"**, which opens a new conversation and **sends the question there right away** (D2). |
| **Decline** | One or two friendly sentences saying the learner's documents don't cover this. It must not look like an error. Two variants: the question belongs to another of the learner's subjects → **"New conversation"** that carries and sends the question (as above); it fits none of their subjects → say that a document on the topic is needed to continue, with **"Upload a document"** as the only action (D4). |
| **No active documents in these subjects** | All documents in the conversation's subjects were archived: "There are no active documents in this conversation's subjects." with a link to the Library (Archived tab). History stays readable. |
| **Summarize lesson** | "Summarize lesson" in the header → progress → confirmation with a link to the note. If a note exists, the action reads "Update lesson note". **If the learner edited that note**, confirm first: "You've edited this note. Replace it with a new summary?" (Replace / Cancel). |
| **Archived conversation** | Banner "This conversation is archived." with **"Restore"**; input disabled. |
| **Rate limited** | Too many messages (20 per minute, 500 per day): inline message with the time the learner can send again, in GMT+7 (D8); input disabled until then. |
| **Error** | The answer failed: a short message and **"Retry"**. |
| **Started from a note** | Top of the conversation: "Started from note: *Note title*" with a link. |

**Status line.** A slim line under the input shows this conversation's token usage, e.g. "Tokens: 12,480 in · 3,215 out", updated after each completed answer.

### 6.7 Conversations — US-13
- List: title (from the first question), subject chips (up to 3), last activity, note indicator; newest first.
- Filters: date range and subject (any of the conversation's subjects); Active / Archived tabs.
- Row actions: open, archive / restore.
- Opening a conversation shows its history (§6.6) and its **Lesson Note** (link or side panel).
- Empty states: no conversations yet (with "Start a conversation"); no results for these filters.

### 6.8 Notes — US-7, US-13b
- **List:** title, subject chips, date, link to the source conversation; same filters and tabs as §6.7.
- **Note editor:** Markdown editor with preview; save; **Archive** / Restore; **"Discuss this note"** (starts a new conversation with the note's subjects and a link back); link to the source conversation.
- Show when a note has been edited since it was generated ("Edited"), since that triggers the overwrite confirmation in chat.

### 6.9 Subjects — US-10b
- List of **my subjects** (subjects of the learner's ready, non-archived documents): name, number of documents, number of conversations.
- **Rename** inline. If renamed, show the shared name beneath in muted text ("Shared name: Large Language Models") and **"Reset name"**.
- Rename feedback: must differ from the learner's other subject names; same checks and helper text as §6.4. It may equal the name of a shared subject the learner doesn't have, with no warning (D6). Make clear the rename is **personal**: "Only you see this name."
- Clicking a subject filters the Library by it.
- There is no "create subject" or "delete subject" here; subjects come from documents.

### 6.10 Usage — US-9
- Totals: input and output tokens, for today (the GMT+7 day, D8) and all time.
- Three sections: **Conversations** (per conversation, sortable), **Document processing** (per document the learner's upload processed first), **Background** (notes and learning records).
- One line explaining that a document Smart Tutor had already processed costs nothing.
- No limits, credits, or upgrade prompts.

### 6.11 Settings
Removed in v0.5: no Settings page in Release 1 (PRD Q45).

## 7. Release 2: research map (low-fidelity wireframes) — US-19, US-20

Wireframes only, to agree on structure. The map is per subject.

| Screen / state | Key content |
|---|---|
| **Research map** | Subject selector; **timeline** of the learner's works by year; arrows for citation links between works they hold; one node per work (several files of the same paper collapse into one). Works without a year are listed separately. |
| **Work details** | From a node: title, authors, year, the learner's file(s), cites / cited by (within the library). Each link opens the citing passage's page. |
| **Reading order** | A numbered list for the subject (foundational works first), each step with a one-line reason (e.g. "Cited by 3 later papers"). |
| **Ask about a reading path** | Entry point from the map ("How did *idea* develop?") that opens a chat answer walking the works in order with citations. |
| **Sparse map** | A subject with 0–1 works, or no links found: explain what's missing (e.g. "Add more papers in this subject to see how they connect"). |

## 8. Release 3: learning loop (low-fidelity wireframes) — US-14, US-15, US-16

| Screen | Key content |
|---|---|
| **Generate quiz** | Select 1–10 active notes in the Notes list → **"Generate quiz"** → progress (up to ~15 s). |
| **Take quiz / results** | 5–10 multiple-choice questions, 4 options, one correct; results with score, correct answers, explanations, score per topic; retake; flag a question. |
| **Quizzes list** | Same list pattern (date, subject, Active / Archived). |
| **Reports** | Daily / weekly reports across all subjects: topics learned, conversations, quiz results, weak topics, recommendations; **"Generate now"**. |
| **What should I learn next?** | 3–5 cards: subject, topic, reason (e.g. "quiz score 40%", "next in reading order"), where to read (document, page), **"Start learning"**. |

## 9. Content for mockups

Use this realistic sample data, not lorem ipsum.

**Learner:** Mai, PhD student, time zone Asia/Ho_Chi_Minh.

**Subjects** (shared name → Mai's name if renamed):
- Large Language Models → renamed by Mai to **LLMs**
- AI Agents
- Retrieval-Augmented Generation
- Reinforcement Learning (used for the fourth-subject example)

**Library** (title — authors, year — subjects — state):
- *Attention Is All You Need* — Vaswani et al., 2017 — LLMs — Ready
- *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models* — Wei et al., 2022 — LLMs, AI Agents — Ready
- *ReAct: Synergizing Reasoning and Acting in Language Models* — Yao et al., 2022 — AI Agents — Ready
- *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks* — Lewis et al., 2020 — Retrieval-Augmented Generation — Ready
- *Toolformer: Language Models Can Teach Themselves to Use Tools* — Schick et al., 2023 — AI Agents, LLMs — Choose subjects
- *Agentic Design Patterns* (book, no year shown) — no subjects yet — Processing
- *lecture-03-scan.pdf* — Failed: "No text layer (scanned PDFs are not supported yet)"
- *Proximal Policy Optimization Algorithms* — Schulman et al., 2017 — Reinforcement Learning — Ready

**Suggestions for Toolformer:** AI Agents (Your subject), Large Language Models shown as "LLMs" (Your subject), Tool Use (New).

**J2/J3 conversation:**
1. "How does ReAct combine reasoning and acting?" → detected: **AI Agents**; cited answer (*ReAct…*, p. 3).
2. "How does retrieval reduce hallucination in that loop?" → "Added Retrieval-Augmented Generation to this conversation".
3. "How does self-attention work?" → "Added LLMs to this conversation" + the maximum notice.
4. "How does PPO clip the policy update?" → matches **Reinforcement Learning**, a fourth subject → not answered; **"New conversation"**.
5. A decline example: "What's the best laptop for research?" → not covered by Mai's documents.

**Landing page copy** (§6.0; quoted text is required):
- Headline: "Ask your own documents. Get answers you can check."
- Sub-line: "Upload your PDFs. Smart Tutor answers only from them and shows the title and page for every answer."
- Buttons: "Create an account" (primary), "Sign in" (secondary). Below them: "Pilot · laptop browsers only."
- How it works: "Upload your PDFs" · "Ask a question" · "Check the page it came from".
- Trust points: "Only your documents: the tutor never answers from anything else." · "Private to you: no one else sees your documents, conversations, or notes." · "Every answer cites the document title and page." · "A pilot for laptop browsers."

## 10. Visual, interaction, and accessibility requirements

- **Brand:** none yet. Propose one direction (logo mark, palette, type). Favor a reading-friendly, document-centric feel: generous line height for answers, a clear typographic distinction between the tutor's words and quoted or cited material.
- **Screen sizes:** laptop only; design at 1440 px wide and check at 1280 px. No phone or tablet breakpoints.
- **States have a consistent visual language:** processing (neutral, animated), needs action (attention color), ready (success), failed (error), archived (muted). Never use color alone; pair each with a label or icon.
- **Subject chips:** one consistent chip component everywhere (Library, picker, chat header, lists). Subject chips may carry a stable color per subject; keep text contrast AA.
- **System notices in chat** (subject added, maximum reached) must look different from both tutor and learner messages.
- **Accessibility:** WCAG 2.1 AA (contrast, keyboard navigation, visible focus, labelled controls). Streaming text must not be announced word by word; announce processing state changes and upload results through a polite live region. The drop zone needs a keyboard-accessible "Upload" button.
- **Themes:** light mode required; dark mode optional.
- **Components page:** app shell, filter bar, tabs, table row, document state badge, upload tray item, drop zone, subject chip, subject picker, citation, system notice, banner, empty state, dialog, side panel, status line, toast.

## 11. Deliverables for each round

1. The four flows in §5 as clickable prototypes.
2. Every Release 1 screen and state in §6, named `<screen>-<state>@v<brief version>` (e.g. `library-choose-subjects@v0.3`).
3. Wireframes for §7 and §8.
4. The components page (§10).
5. A short list of questions or proposed changes to this brief.
6. A prototype that tools can read (applies from the next round). Expose every state in `window.ST.STATES` as `{ id, group, ref, desc }`, where `ref` names the brief section and the specific user stories of that state (`§6.6 · US-3b`, not a range such as `US-3–10`). Open any state at `index.html#/<state-id>`, and hide the design-review chrome when the URL has `?shot=1`. The coding team renders states from these URLs (`sdd/specs/2026-10-03-design-to-code-loop-design.md` §5.1).

## 12. Open questions

| # | Question | Default if unanswered |
|---|---|---|
| Q4 | Should the citations switch also apply to Lesson Notes when citations are carried into notes (Release 3)? | Yes, the same remembered setting. |
| Q5 | Can the learner upload several files at once? | Yes: multi-select and drag-and-drop of several PDFs, each with its own row; upload limits still apply. |
| Q8 | Should the first suggestion be pre-selected? | Yes (one-click accept); measured against the PRD target that ≥ 70% of documents keep a suggested subject. |

**Answered**

| # | Question | Answer |
|---|---|---|
| Q1 | How far must the web app work on phones? | Not supported; laptop only (v0.2). |
| Q2 | Should citations always show? | Shown by default, with a switch to hide or show them (v0.2). |
| Q3 | Where does per-conversation token usage live? | In the status line of the chat (v0.2). |
| Q7 | Should a document's subjects be choosable while full processing is still running? | No: subjects are chosen once processing has finished (v0.4; PRD v2.7 US-2b). |

**Note for the PRD owner:** Q1–Q3 were added to PRD v1.6 on a branch that was not merged; PRD v2.7 does not mention them yet.

## 13. How this brief is versioned

- **One file, many versions.** This file is edited in place; git keeps history. The version in the header changes on every update that reaches the designer.
- **Numbering:** `v0.x` until the Release 1 design is approved, which makes it `v1.0`. Before `v1.0`, every update increases the minor number, including rewrites. After `v1.0`, increase the minor number for refinements and the major number when scope changes (e.g. `v2.0` when the research map moves to full fidelity).
- **Every new version:**
  1. update the version, date, and the PRD version it is based on;
  2. rewrite **§0 What changed**, listing the screens to redo;
  3. add a row to the changelog;
  4. record review decisions in the feedback log, and close or add open questions in §12.
- **Keep it in sync with the PRD.** When the PRD changes a user-facing behavior, the brief gets a new version in the same pull request or the next one.

### Changelog

| Version | Date | PRD | Changes | Screens to redo |
|---|---|---|---|---|
| v0.6 | 2026-10-06 | v2.15 | Joins the two parallel v0.5 versions below; upload-rights line in the Library (G2); no terms link on the landing page; sign-out returns to the landing page (G4). | `library-empty`, `library-default` and other drop-zone states; `landing-default` footer |
| v0.5 | 2026-10-06 | v2.14 | Scope cut by the owner: no terms of use step, no Settings page; Q6 dropped. | Remove `terms-first-run`, `terms-accepted`, `settings-default`; navigation without Settings |
| v0.5 (PR #89) | 2026-10-06 | v2.14 (#89) | Public landing page at `/` (§6.0, copy in §9), text only; Keycloak pages reduced to stock layout with logo, colors, font, and display name (§6.2); J1 starts on the landing page; sign-out returns to it; §9 sample fixes (E1, E2). | New `landing-default`; reduce `auth-*`; J1. |
| v0.4 | 2026-10-04 | v2.7 | Owner decisions on round 2: subjects chosen after processing (Q7); carried question sent right away (D2); no-subject decline asks for a document to continue (D4); rename may match another shared name (D6); subjects of archived documents can change (D7); GMT+7 for limits and "today" (D8); thumbs with labels (D1), fourth-subject wording (D3), and calmer Library rows (D5) accepted; scanned-PDF failure wording; prototype contract (§11 item 6). | Only the states in §0. |
| v0.3 | 2026-10-03 | v2.1 | Rewrite for learner-uploaded documents: Library home, upload and processing states, subject picker (3 suggestions, keep 1–3, shared names), document details, Subjects (personal rename), multi-subject chat with growth notices and a 3-subject maximum, processing usage; enrollment and "Change subject" removed; R2 research map wireframes; learning loop moved to R3; four review flows; new sample data. | All. New: Library, Choose subjects, Document details, Subjects, Terms. Removed: Subject enrollment. |
| v0.2 | 2026-10-02 | v1.6 | Laptop only; citations switch (on by default); token usage in the chat status line. | Chat (all states); all screens drop phone variants |
| v0.1 | 2026-10-02 | v1.5 | First brief: Release 1 screens at full fidelity, Release 2 as wireframes. | All |

### Feedback log

| Round | Brief version reviewed | Feedback | Decision | Applied in |
|---|---|---|---|---|
| 0 (owner) | v0.1 | Answers to Q1–Q3. | Laptop only; citations switch, on by default; usage in the chat status line. | v0.2 |
| 1 (owner) | v0.2 | PRD v2.1 changed the product (own documents, shared subjects, multi-subject threads, new release order). | Rewrite the brief. | v0.3 |
| 2 (owner) | v0.3 | Round 2 accepted as `design-v0.3`. Checked against PRD v2.2 (architecture only) and v2.3 (`pypdf`, no OCR). One user-facing gap: a scanned PDF without a text layer fails with "No text layer (scanned PDFs are not supported yet)", not "We couldn't read this PDF" (`library-failed`, `details-failed`). | Accept v0.3; code follows the PRD wording. Designer's Q7 and D1–D12 stay open for the PO; story tickets list them where they apply. | v0.4 |
| 2 (owner) | v0.3 | Answers to the designer's Q7 and D1–D8. D9–D12 were notes. | Q7 no; D2 yes; D4 decline and tell the learner to upload a document to continue, no "New conversation"; D6 allowed; D7 allowed; D8 GMT+7 for everyone. D1, D3, D5 accepted as proposed (recommended by Claude). The owner accepted the longer wait before choosing subjects (Q7) and GMT+7 for everyone (D8) as they are. PRD v2.7. | v0.4 |
| 3 (designer) | v0.4 | Round 3 delivered: 101 states (new `chat-decline-other-subject`, `picker-change-subjects-archived`). Questions E1–E10 on the prototype's questions page: E1 §9 sample still says "We couldn't read this PDF" for the scan; E2 §9 shows a processing document with a subject; E3 which decline id is which; **E4 when the "another subject" decline can happen at all** (with < 3 subjects the thread grows, at 3 the fourth-subject refusal applies); E5 proposed chat hint "1 is processing, 1 needs subjects"; **E6 the declined question is not kept after "Upload a document"**; **E7 subjects added to an archived document don't show in Subjects until restore**; **E8 daily limits reset at midnight GMT+7?**; E9 user stories per state were guessed (Claude corrected 10 against the PRD); E10 a separate state for D6. | Open for the owner (bold ones change behavior). E1, E2: fix §9 sample data next version. | E1, E2: v0.5 |
| 4 (owner) | v0.4 | A public landing page with an overview of Smart Tutor; as little Keycloak customization as possible. Discussed with PO and UX reviewers (`sdd/reviews/2026-10-06-landing-page-discussion.md`). | Landing page at `/`, text only, same page for signed-in visitors; Keycloak stock layout with logo, colors, font, display name; terms stay in the app (superseded by Q45). PRD v2.14 (#89). E4, E6, E7, E8 still open. | v0.5 |
| 4 (owner) | v0.4 | Product owner removed the terms of use step and the Settings page from Release 1 (tickets #46, #49, #50). | Drop `terms-first-run`, `terms-accepted`, `settings-default` and the Settings navigation item; Q6 no longer applies. PRD v2.14 (Q45). | v0.5 |
| 5 (designer) | v0.5 | Round 4 delivered: 102 states (new `landing-default`; `auth-*` reduced to Keycloak's stock layout). Claude removed a focus ring that framed the whole page after each route change (`main[tabindex="-1"]`). Questions: **F1** turn on Keycloak's "Email as username" so registration has no Username field (a realm setting, not theming); F2 keep "Sign in" for signed-in visitors on the landing page (decided: yes, Q46); **F3** the footer "Terms of use" link needs a public `/terms` page (moot in v0.6: no terms link); **F4** keep "Remember me" and "Forgot password?" on the Keycloak login? | Open for the owner (bold ones change behavior or Keycloak settings). | — |
| 5 (designer) | v0.5 | Round 4 applied the scope cut on top of the landing page. G1 two different v0.5 briefs; G2 the terms checkbox held the upload-rights confirmation; G3 Settings held the theme and the citations default (both already elsewhere, note only); G4 where sign-out goes. F1 email as username; F2 "Sign in" for a signed-in visitor. | G1 merged into v0.6; G2 one line "Only upload documents you have the right to use." under the drop zone, nothing to accept; G3 noted; G4 the landing page (keep). F1, F4 and E4, E6, E7, E8 still open; F3 moot. PRD v2.15 (Q46, Q47). | v0.6 |

---

## Appendix A — Prompt to start a round in Open Design

Paste this, together with this file, to start or continue a round:

> You are designing **Smart Tutor**, a laptop web app (1440 px, light mode) where learners upload their own PDFs and ask a tutor that answers only from them, with citations. Follow the attached design brief **v0.6** exactly; it is the source of truth. Start with **§0 What changed**: this round updates the existing prototype in this project, so change only what is listed there and keep everything else as it is. Keep (1) the four clickable flows in §5 working, (2) every Release 1 screen and state in §6, (3) the wireframes for §7 and §8, and (4) the components page (§10). Use the sample data in §9 and the quoted wording verbatim. Name each frame `<screen>-<state>@v0.6`. Do not design anything listed as out of scope in §4. Follow the prototype contract in §11 item 6: every state in `window.ST.STATES` with its specific user stories in `ref`, each state at `index.html#/<state-id>`, and review chrome hidden when the URL has `?shot=1`. End with a list of questions or proposed changes to the brief.
