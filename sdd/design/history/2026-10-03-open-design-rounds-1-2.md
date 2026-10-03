# Open Design conversation: Smart Tutor design rounds 1–2

Exported 2026-10-03 from Open Design project `5632ee5d-5009-4b7b-86a1-827855c84d52` ("Smart Tutor Design Round 1"). Read-only record of the designer's questions, the owner's answers, and the designer's plans. Pasted design briefs are replaced by a pointer; the brief itself is versioned in `sdd/design/brief.md`.

## Smart Tutor Design Round 1

### Owner · 2026-10-02 04:37 UTC

*Pasted design brief v0.2 (12,400 characters). See `sdd/design/brief.md` and its git history.*

### Designer (Claude) · 2026-10-02 04:37 UTC

I've read brief v0.2 and can work from it. Before planning I need answers to three questions, because each one changes the whole set of deliverables.

- **Brand conflict.** The project has the **Cisco design system** turned on. It's a dark, navy and charcoal enterprise look. Your brief asks me to propose a new Smart Tutor brand (logo mark, palette, type) and requires light mode. A calm study tool doesn't fit Cisco's look well, and following it would change every screen.
- **Phone frame.** The workspace marked this request as a phone app. §4 says laptop only, so I'll ignore that and design at 1440 px, checked at 1280 px, with no device frame.
- **Size of the job.** There are about 25 named screens and states, plus Release 2 wireframes, a components page and a list of questions for you. How I package them decides whether you review one clickable prototype or a folder of separate pages.

<question-form id="smart-tutor-r1" title="Three decisions before I plan round 1">
{
  "description": "Each question has a recommended answer selected. Submit as-is to accept them all.",
  "questions": [
    {
      "id": "brand_basis",
      "label": "Which visual basis should I use?",
      "type": "radio",
      "default": "own-brand",
      "options": [
        { "label": "New Smart Tutor brand, light mode (as the brief says)", "value": "own-brand" },
        { "label": "The active Cisco design system, adapted to light mode", "value": "cisco-light" },
        { "label": "The Cisco design system as it is (dark)", "value": "cisco-dark" }
      ],
      "required": true
    },
    {
      "id": "packaging",
      "label": "How should the deliverables be packaged?",
      "type": "radio",
      "default": "single-prototype",
      "options": [
        { "label": "One clickable prototype with an index linking to every named state", "value": "single-prototype" },
        { "label": "One HTML page per screen-state, plus an index page", "value": "per-state-files" }
      ]
    },
    {
      "id": "dark_mode",
      "label": "Include the optional dark mode this round?",
      "type": "radio",
      "default": "light-only",
      "options": [
        { "label": "Light only; dark mode in a later round", "value": "light-only" },
        { "label": "Light and dark, with a theme switch", "value": "light-and-dark" }
      ]
    }
  ]
}
</question-form>

### Owner · 2026-10-02 04:40 UTC

[form answers — smart-tutor-r1]
- Which visual basis should I use?: New Smart Tutor brand, light mode (as the brief says) [value: own-brand]
- How should the deliverables be packaged?: One clickable prototype with an index linking to every named state [value: single-prototype]
- Include the optional dark mode this round?: Light and dark, with a theme switch [value: light-and-dark]

### Designer (Claude) · 2026-10-02 04:40 UTC

Thanks, the plan is now set. I'll build one clickable prototype for the Smart Tutor laptop web app, using a new brand of my own, in light and dark mode.

**Visual direction:** a quiet, library-like study tool. Backgrounds are cool off-white in light mode and slate in dark mode. One deep teal accent marks actions and citations. Headings use a serif typeface and body text uses the system sans. The logo is an open-book mark with a small citation tick.

**Deliverables**
- `index.html` is the single prototype. A left-hand index links to every named state, for example `chat-decline@v0.2` and `notes-editor@v0.2`, and the app itself is clickable from one screen to the next.
- It covers:
  - every Release 1 screen and state in §5
  - Release 2 low-fidelity wireframes (§6)
  - a components page (§8)
  - a page of questions and proposed changes to the brief

**Key constraints**
- Laptop only: designed at 1440 px and holding at 1280 px, with no phone frame.
- Copy the brief marks as required is used word for word.
- "Delete" is always "Archive", and there is never a permanent-delete action.
- Citations are on by default and the switch is remembered across conversations.
- Token usage sits in the chat's bottom status line.
- WCAG 2.1 AA, with each theme's contrast set separately.
- Streaming text is not read out word by word by screen readers.
- The active Cisco design system is not used, as you chose.

**Assumptions**
- The Keycloak sign-in, sign-up and email-verification pages are shown as themed mock-ups, not working sign-in.
- Streaming, rate limits, summary generation and errors are simulated in the prototype.
- Q4 uses its default: in Release 2, Lesson Notes follow the same remembered citations setting.
- The serif and sans typefaces come from the computer itself, not downloaded web fonts, so the file works offline.

**Risks**
- The prototype will be one large file.
- Headings will look slightly different on Mac and Windows, because the system serif typeface differs.

### Designer · 2026-10-02 04:41 UTC

I've written the styles and the entry page. Next come the sample data and the screen logic.The Release 1 screens are written. Next: the Release 2 wireframes, the components page, the questions page, and the list of states that ties everything together.

Round 1 for brief v0.2 is ready as one clickable prototype. Open `index.html` to start; it lands on an overview page that links to all 54 named states, each labelled like `chat-decline@v0.2`. I didn't open or test it in a browser, so nothing has been checked on screen yet.

**How to get around**
- A dark bar across the top is for reviewing only, not part of the app. It shows the current state's name and has Prev / Next, a light/dark switch and an **All states** list.
- The app also works as a normal flow: sign in, choose subjects, ask a question, summarize it into a lesson note, archive and restore.

**What's covered**
- **Sign in / sign up (§5.2):** the Keycloak sign-in, registration and email-verification pages with the new brand applied. The registration page shows an example of a field error.
- **Subject enrollment (§5.3):** the first-run screen with Continue disabled until a subject is chosen, the subjects list with enroll / leave, and the leave confirmation.
- **Chat (§5.4):** all 17 states, including streaming with Stop, the citations switch on and off, and the friendly decline using the required wording.
  - The citations switch is on by default and remembered across conversations.
  - Token usage sits in the status line under the input and updates after each answer.
  - Screen readers hear "answering" and "answer ready", not each word as it streams.
- **Conversations and Notes (§5.5–5.6):** one shared list layout with working date and subject filters, Active / Archived tabs, archive with Undo, and empty states. The note editor shows Markdown and preview side by side.
- **Usage and Settings (§5.7–5.8):** totals plus a sortable table of conversations, and time zone taken from the browser.
- **Release 2 (§6):** low-fidelity wireframes shown inside the real app shell, so you can check the navigation fits.
- **Components page and a questions page:** the questions page has 12 items for you.

**Decisions to check**
- The brand is my proposal, as the brief asked. The colours are cool neutrals with one deep teal accent. The logo is an open book with a tick on the right-hand page. Each theme's contrast was chosen separately to meet AA.
- Headings use whatever serif the computer has (Charter or similar), so they look slightly different on Mac and Windows. If you approve the direction, a licensed web font would fix that.
- I added three behaviours the brief doesn't specify:
  - "Change" opens a new conversation under the chosen subject with the first question already filled in.
  - "New conversation" from a decline carries the declined question over.
  - Settings gets an Appearance section for the theme.

  All three are written up on the questions page; please confirm or reject them.
- Q4 uses its default: the same citations setting will apply to Lesson Notes in Release 2.
- I didn't have PRD v1.6, so I couldn't check the brief against it.
- Streaming, rate limits, summarizing and errors are simulated. The Keycloak pages are mock-ups, not a real sign-in.

**Files**
- `index.html`
- `styles.css`
- `js/` (6 files)

### Owner · 2026-10-03 01:31 UTC

*Pasted design brief v0.3 (28,938 characters). See `sdd/design/brief.md` and its git history.*

### Designer (Claude) · 2026-10-03 01:31 UTC

The v0.3 rewrite doesn't need any new answers from you, so the plan below is ready to build. Your round 1 decisions carry over:
- the Smart Tutor brand I proposed (cool neutral backgrounds, one deep teal accent, serif headings, the open-book logo);
- one clickable prototype with an index of every named state;
- light and dark themes.

The product underneath is rebuilt from scratch for v0.3.

**Goal:** design round 2 for brief v0.3: the Release 1 "your own documents" web app at full fidelity, linked into the four review flows J1–J4, plus low-fidelity wireframes for Release 2 (research map) and Release 3 (learning loop).

**Deliverables**
- `index.html` becomes the v0.3 prototype. It has:
  - an overview page;
  - each state labelled `<screen>-<state>@v0.3`;
  - a "Flows" section that walks J1–J4 step by step.
- Screens covered:
  - **App shell:** Library badge and the upload tray.
  - **Sign-in pages and terms:** the Keycloak theme and the in-app terms step.
  - **Library:** all 11 states.
  - **Choose subjects:** the picker, including stepping through several documents.
  - **Document details:** the side panel.
  - **Chat:** all 17 states.
  - **Lists, Subjects, Usage, Settings:** Conversations, Notes with the "Edited" marker, Subjects with personal rename, Usage with its three sections, and Settings.
- R2 and R3 wireframes, an expanded components page, and a new questions page.
- The v0.2 prototype moves to `v0.2/` so you can still open it for reference.

**Changes from round 1 to the visual system**
- Subject chips get a stable colour per subject. The text inside always meets AA contrast and the chip always shows the name.
- Document states each pair a colour with an icon and a label: processing, needs action, ready, failed, archived.
- Chat system notices get their own style, distinct from both the tutor's and the learner's messages.
- Answers get more generous line height. Quoted text from documents is set apart from the tutor's own words.

**Key constraints**
- Required wording is used word for word.
- No Share, delete or download actions; Archive replaces delete everywhere.
- Subject names are shown as the learner's renamed version wherever they appear.
- The picker warns that subject names are visible to everyone.
- Nothing in the UI reveals that another user has the same file.
- Laptop only, at 1440 px and checked at 1280 px; WCAG 2.1 AA.

**Assumptions**
- Open questions use the brief's defaults:
  - Q4: the citations switch also covers Lesson Notes.
  - Q5: several files can be uploaded at once.
  - Q6: terms are accepted in the app.
  - Q7: subjects can be chosen while processing continues.
  - Q8: the first suggestion is pre-selected.
- The example-questions slot in a new conversation is shown and marked optional.
- Uploads, processing, detection, streaming and rate limits are simulated. Dropping or picking real files creates simulated rows.
- The sample papers are real, but I'll show a document icon rather than covers or page thumbnails.

**Risks**
- This is a large single prototype.
- Headings use the computer's own serif typeface, so they look slightly different on Mac and Windows.

### Designer · 2026-10-03 01:32 UTC

The core, styles and sample data are rewritten for v0.3. Next are the document screens: Library, the subject picker, document details and Subjects.Chat, the lists, the note editor, Usage and Settings are written. Last come the overview with the four flows, the R2 and R3 wireframes, the components and questions pages, and the list of states.

<od-done key="bd1bd648858880d9"/>

Round 2 for brief v0.3 is ready: open `index.html`. It lands on an overview with the four flows (J1–J4) and links to all 98 states, each named like `library-choose-subjects@v0.3`. I haven't opened it in a browser, so nothing has been checked on screen yet. The round 1 prototype is kept for reference in `v0.2/index.html`.

**How to review**
- Click **Walk through J1** (or J2–J4) on the overview. The bar across the top, which is review-only and not part of the app, then shows which step you're on, and Prev / Next follow that flow.
- On Library screens the same bar has **Simulate drop · 3 PDFs**. You can also drop or pick real PDFs; they get simulated upload and processing.
- Once inside the app, clicking around keeps what you've done.

**What's covered**
- **Library:** all 11 states from §6.3, including a drag-over state and a second "could not be processed" example. The upload tray stays visible on every screen, and the Library badge counts documents that need you.
- **Choose subjects:**
  - three suggestions labelled "Your subject", "Shared subject" or "New", with the first one pre-selected;
  - typing an existing subject's name in a slightly different form (e.g. "LLM") shows "We'll use the existing subject *Large Language Models*", and typed names can also be rejected or hit the 60-character limit;
  - the required "Subject names are visible to everyone" helper;
  - stepping through several documents ("1 of 3", Skip).
- **Document details:** a side panel where you can edit the title (with "Reset to extracted title"), archive or restore, and retry a failed file.
- **Chat:** every §6.6 state, using the §9 script.
  - Up to 3 subject chips, with notices when a subject is added and when the maximum is reached.
  - A fourth subject is refused, and "New conversation" carries the question over and answers it.
  - Text quoted from a document is visibly separate from the tutor's own words.
  - The citations switch, the edited-note confirmation and the token status line are all there.
- **Other screens:** Conversations and Notes (with the "Edited" marker), Subjects with a personal rename, Usage in three sections, and Settings with the accepted terms.
- **Release 2 research-map and Release 3 learning-loop wireframes**, a components page and a questions page.

**Things to check**
- **Q7 conflict with the PRD:** I used the brief's default, so subjects can be chosen while processing continues. PRD §9.5 says otherwise and needs aligning.
- **Thumbs:** I used outline thumb icons instead of the 👍 / 👎 emoji in the brief.
- **Fourth-subject wording:** the refusal message is my wording, since the brief doesn't give any.
- **Carrying a question over:** the new conversation sends the carried question straight away, so the learner doesn't press Send again.
- **Library rows:** each row shows one button that fits its state, and the other actions sit in a "More" menu.
- **Extra sample paper:** I added *Language Models are Few-Shot Learners* as an archived document so the Archived tab and archived citations have something to show.
- **Research map links:** the citation arrows are illustrative placeholders, apart from ReAct citing Chain-of-Thought.

All of these are on the questions page, along with two decisions I need from you: whether a learner can rename a subject to another shared subject's name, and the question-carrying behaviour above.

**Files**
- `index.html`
- `styles.css` and `v03.css`
- `js/` (7 files)
- `v0.2/` (round 1, kept for reference)
