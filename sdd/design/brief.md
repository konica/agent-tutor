# Smart Tutor — Design Brief

| | |
|---|---|
| **Brief version** | v0.1 |
| **Based on** | `sdd/prd.md` Draft v1.5 |
| **Status** | Draft, round 1 |
| **Owner** | Thao Dinh |
| **Last updated** | 2026-10-02 |
| **Designer** | Open Design |

> **For the designer:** this brief is the source of truth for the mockups. If the brief and the PRD disagree, follow the brief and flag the conflict. Label every deliverable with the brief version it answers (e.g. `chat-thread@v0.1`). Read **§0 What changed** first on every new version.

---

## 0. What changed in this version

First version. Design every Release 1 screen in §5. Release 2 screens (§6) are low-fidelity wireframes only.

---

## 1. Product in one paragraph

Smart Tutor is a web app where a learner enrolls in study subjects (e.g. *IELTS*, *AI Agents*) and asks questions. The tutor works out which subject a question belongs to, answers **only from that subject's documents**, and shows where each answer came from (document title and page). When the documents don't cover a question, it politely says so instead of guessing. Learners turn conversations into **Lesson Notes** and revisit them later. Release 2 adds quizzes, daily/weekly reports, and "what should I learn next" recommendations.

## 2. Who we are designing for

| Persona | What they need from the UI |
|---|---|
| **Learner** (only persona with screens) | Ask without setup; trust the answer (see the source); stay on track; find past conversations and notes quickly. |
| Admin | **No screens.** Admins work in S3 and LangSmith. Do not design admin pages. |

Tone: calm, focused study tool. Friendly, never chatty. Plain English.

## 3. Design principles

1. **Trust is visible.** Every answer shows its citations. The thread's subject is always on screen.
2. **No setup before asking.** The learner never picks a subject to start chatting; the tutor detects it.
3. **Declines are helpful, not errors.** A decline explains why and offers the next step ("New conversation").
4. **Nothing is lost.** "Delete" is always "Archive", and archived items can be restored. Never show a permanent-delete action.
5. **One management pattern everywhere.** Conversations, notes, quizzes and reports share the same list layout: filter by date range and subject, Active / Archived tabs, archive and restore.

## 4. Scope

**In scope for this round:** the Release 1 learner web app (§5), desktop first, plus a responsive layout down to phone width (see open question Q1).

**Out of scope (do not design):**
- Admin UI, document upload screens, the content-gap report.
- Token credits, plans, or billing (usage is shown, not limited).
- Web search, note sharing, notifications (email/push), languages other than English, native mobile apps.
- Keycloak's login and registration pages beyond a **theme** (they are hosted by Keycloak; we only restyle them).

## 5. Release 1 screens (full fidelity)

Each screen lists the PRD user story it implements. Copy in quotes is required wording; the designer may refine everything else.

### 5.1 App shell
- Left navigation: **Chat** (new conversation), **Conversations**, **Notes**, **Subjects**, **Usage**, **Settings**. Release 2 adds **Quizzes** and **Reports**; leave room for them.
- User menu: name, sign out.

### 5.2 Sign in / sign up — US-1
- Theme for Keycloak's hosted pages: logo, colors, typography applied to the standard login, registration, and email-verification pages.
- After first sign-in the learner lands on **Subject enrollment** (5.3).

### 5.3 Subject enrollment — US-2
- Grid or list of all subjects with name and short description; enroll / leave toggle.
- First-run version: heading that explains "Choose the subjects you're studying", a continue button disabled until at least one subject is chosen.
- Leaving a subject: confirm dialog explaining that its conversations become read-only until the learner enrolls again.

### 5.4 Chat — US-3, US-4, US-5, US-6, US-7, US-9
The most important screen. Design every state:

| State | What the learner sees |
|---|---|
| **New conversation (empty)** | Prompt input, a few example questions per enrolled subject, no subject picker. |
| **Subject detected** | After the first answer, a subject chip in the thread header (e.g. "IELTS") with a **"Change"** action. "Change" restarts the conversation under the chosen subject. |
| **Detection unsure** | Tutor message "Which subject is this about?" with one button per enrolled subject. |
| **Streaming answer** | Text appears progressively; a stop button. |
| **Answer with citations** | At least one citation per answer: document title and page (e.g. "Agentic Design Patterns, p. 42"). Citations from archived documents show an "archived" badge. Thumbs up / down on each answer, with an optional reason. |
| **Decline (off-subject or not covered)** | One or two friendly sentences: "This conversation is about *IELTS*. Please ask a question about *IELTS*, or start a new conversation for other topics." plus a **"New conversation"** button. Must not look like an error. |
| **Summarize lesson** | A **"Summarize lesson"** action in the thread header. While generating: progress state. After: confirmation with a link to the note. If a note already exists, the action reads "Update lesson note" and warns that it overwrites the previous version. |
| **Read-only thread** | Banner when the learner left the subject ("Enroll in *IELTS* again to continue") or the thread is archived ("Restore to continue"). Input disabled. |
| **Rate limited** | Inline message: too many messages, try again in N seconds. Input disabled until then. |
| **Error** | The answer failed: retry action. |

Also show: the thread's token usage (small, unobtrusive, e.g. in a thread info panel) and, when the thread has a note, a link to it.

### 5.5 Conversations — US-13
- List: title (from first question), subject, last activity; newest first.
- Filters: **date range** and **subject**, combinable; Active / Archived tabs.
- Row actions: open, archive (or restore in the Archived tab). Rows with a note show a note indicator.
- Opening a conversation shows its history (5.4) and the **linked Lesson Note**.
- Empty states: no conversations yet; no results for these filters.

### 5.6 Notes — US-7, US-13b
- **List:** title, subject, date, link to the source conversation; same filters and tabs as 5.5.
- **Note view / editor:** Markdown editor with preview; save; **archive** / restore; **"Discuss this note"** (starts a new conversation bound to the note's subject, with a link back to the note); link to source conversation.
- A conversation started from a note shows "Started from note: *title*" at the top.

### 5.7 Usage — US-9
- Total input and output tokens; a table of conversations with their tokens, sortable.
- Note that background work (notes, learning records) is included.
- No limits, credits, or upgrade prompts.

### 5.8 Settings
- Time zone (pre-filled from the browser, editable).
- Link to Subjects (5.3).

## 6. Release 2 screens (low-fidelity wireframes only)

Wireframes so we can check the navigation fits; no visual polish yet.

| Screen | PRD | Key content |
|---|---|---|
| **Generate quiz** | US-14 | Select 1–10 active notes in the Notes list; **"Generate quiz"**; progress state (up to ~15 s). |
| **Take quiz** | US-14 | 5–10 multiple-choice questions, 4 options each, one correct; submit. |
| **Quiz results** | US-14 | Score, correct answer and short explanation per question, score per topic; retake; flag a question. |
| **Quizzes list** | US-14 | Same list pattern (date, subject, Active/Archived). |
| **Reports list and report view** | US-15 | Daily / weekly reports across all subjects: topics learned, conversation count, quiz results, weak topics, recommendations; **"Generate now"**. |
| **What should I learn next?** | US-16 | From the Reports screen: "What should I learn tomorrow?" / "…next week?" → 3–5 cards with subject, topic, reason (e.g. "quiz score 40%", "not studied yet"), where to read (document, page), and **"Start learning"**. |

## 7. Content for mockups

Use realistic sample data, not lorem ipsum:
- Subjects: **IELTS**, **AI Agents**.
- Example questions: "How do I structure an IELTS Task 2 essay?", "What is the ReAct pattern?", "What's the difference between a tool and a skill in an agent?"
- Example off-subject question in an IELTS thread: "What is the ReAct pattern?" (should show the decline state).
- Example citations: "Agentic Design Patterns, p. 42"; "IELTS Writing Guide, p. 18".

## 8. Visual and accessibility requirements

- **Brand:** none yet. Propose a direction (logo mark, palette, type) in round 1; one direction is enough.
- **Accessibility:** WCAG 2.1 AA (contrast, keyboard navigation, visible focus, labelled controls). Streaming text must not be announced word by word to screen readers.
- **Themes:** light mode required; dark mode optional in round 1.
- **Components:** build from a small, reusable set (list row, filter bar, tabs, chip, citation, banner, empty state, dialog) and show them on one components page.

## 9. Deliverables for each round

1. Every screen and state listed in §5 (and §6 wireframes), named `<screen>-<state>@v<brief version>`.
2. A components page (§8).
3. A short list of questions or proposed changes to this brief.

## 10. Open questions

| # | Question | Default if unanswered |
|---|---|---|
| Q1 | How far must the web app work on phones? | Responsive to phone width; desktop is the primary target. |
| Q2 | Should the thread show which document chunks were used, beyond citations? | No; citations only. |
| Q3 | Where does per-thread token usage live? | A thread info panel, not in the main chat column. |

## 11. How this brief is versioned

- **One file, many versions.** This file is edited in place; git keeps history. The version number in the header changes on every update that reaches the designer.
- **Numbering:** `v0.x` until the Release 1 design is approved (`v1.0`). Increase the **minor** number for refinements (copy, states, feedback fixes) and the **major** number when scope changes (e.g. `v2.0` when Release 2 screens move to full fidelity).
- **Every new version:**
  1. bump the version, date, and the PRD version it is based on;
  2. rewrite **§0 What changed**, listing the screens the designer must redo;
  3. add a row to the changelog below;
  4. record decisions from review in the feedback log below, and close or add open questions in §10.
- **Keep it in sync with the PRD.** When the PRD changes a user-facing behavior, the brief gets a new version in the same pull request or the next one.

### Changelog

| Version | Date | PRD | Changes | Screens to redo |
|---|---|---|---|---|
| v0.1 | 2026-10-02 | v1.5 | First brief: Release 1 screens at full fidelity, Release 2 as wireframes. | All |

### Feedback log

| Round | Brief version reviewed | Feedback | Decision | Applied in |
|---|---|---|---|---|
| — | — | — | — | — |
