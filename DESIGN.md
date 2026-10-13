# DESIGN.md

How the web app looks and how to build its UI. Read this before writing anything in `web/src/`. The process for turning a ticket's mockup states into code (rendering states, reading the prototype at a round's tag) is in `AGENTS.md` → Design inputs; this file covers what the result must look like.

## Sources

| Need | Read |
|---|---|
| Screens, required wording, accessibility rules | `sdd/design/brief.md` (§6 screens, §10 visual rules) |
| What a state looks like | `make design-shots ROUND=v0.4 STATES="<ids>" THEME=both` (the round in the ticket's `## Design` section); ids in `sdd/design/states.json` |
| Token values | `web/src/styles/tokens.css` (ported from `sdd/design/prototype/styles.css` and `v03.css` at tag `design-v0.3`; **Density** below replaces the type, space, and layout values from round v0.9) |
| Design decisions and open questions | PRD v2.7 (Q38–Q43) and brief v0.4 (§0, Feedback log). The designer's round 3 questions E1–E10 are open; the ticket's `## Design` section says which apply. |

The brand is Smart Tutor's own (`smart-tutor-ds`, light and dark). The Open Design project has the Cisco design system switched on, but the owner chose the own brand instead (2026-10-02, `sdd/design/prototype/history/`); follow the accepted round's tokens, not Cisco.

## Tokens

Every color, font size, space, radius, shadow, and duration in feature code is a `var(--…)` from `tokens.css`. Component dimensions (control heights, icon and avatar sizes, 1–2px borders and gaps) may be literal px. A value the tokens lack goes into `tokens.css` (both themes) first, then gets used.

| Role | Tokens |
|---|---|
| Page and surfaces | `--bg` (page), `--surface` (cards, nav, tables), `--surface-2` / `--surface-3` (hover, headers, quiet fills) |
| Text | `--text`, `--text-2` (secondary), `--text-3` (disabled, placeholders) |
| Lines | `--border`, `--border-strong` (inputs, secondary buttons, dashed empty states) |
| Brand and actions | `--accent` (primary button fill), `--accent-hover`, `--accent-soft` (selected nav item, selected row), `--accent-text` (links, ghost buttons), `--on-accent` |
| Status | `--success`, `--warn`, `--danger`, `--info`, `--attn` (needs the learner's action), each with a `-soft` background |
| Subjects | `--subj-*` hues, used only through the subject chip |
| Focus | `--focus` (2px outline, 2px offset, on `:focus-visible`) |
| Type | `--font-display` (serif: brand word, landing page, empty-state headline only), `--font-body` (system UI; all app headings), `--font-mono` (numbers, ids, token counts; tabular figures); sizes `--fs-12`, `--fs-13`, `--fs-14` (body), `--fs-16`, `--fs-18`, `--fs-20`, `--fs-24`, `--fs-32` (landing), `--fs-64` (landing headline only); `--lh-body` 1.45 (UI), `--lh-read` 1.6 (chat answers, note editor), `--lh-head` 1.25 |
| Space and shape | `--sp-0` (2px), `--sp-1` (4px) … `--sp-6` (24px) in the app; `--sp-8` … `--sp-16` on the landing page only; `--r-sm` 4px, `--r-md` 6px, `--r-lg` 8px (dialogs, drawers), `--r-pill` |
| Motion | `--dur-fast`, `--dur-base`, `--dur-exit`, `--dur-spin`, `--ease-out`, `--ease-in`; everything stops under `prefers-reduced-motion: reduce` |
| Layout | `--nav-w` 208px (`--nav-w-collapsed` 56px), `--page-w` 1200px, `--page-w-wide` fluid up to 1360px (Library and tables), `--chat-w` 720px, `--panel-w` 340px, `--chat-panel-w` 260px (conversation side panel), `--chat-min-w` 480px (conversation beside a document), `--viewer-w` `min(960px, 100% - 64px)` (overlay outside chat), `--tray-w` 320px, `--landing-w` 1120px (landing page column) |

The prototype's `--chrome-*` tokens, `.rb-*` classes, and `od-*` layout primitives belong to the review tool, not the product: leave them out.

## Density

Smart Tutor is a **compact** tool: many features will share the screen, so space goes to content, not chrome (owner, 2026-10-08; brief v0.9 §0). Values below are the targets; `tokens.css` and the shared components follow them from the compact-density foundation ticket.

| Element | Size |
|---|---|
| Body text | `--fs-14`, `--lh-body` 1.45; secondary lines `--fs-13`; table headers, badges, chips, timestamps `--fs-12` (never smaller) |
| Headings | app h1 `--fs-20` sans 650; h2 and dialog titles `--fs-18`; section titles `--fs-14` 600 |
| Controls | button, input, select 32px; in toolbars and table rows 28px; one 36px primary button only on empty states; icon buttons 28px |
| Tables and lists | Library rows 40px, other lists and Usage 32–36px, single line; header row 28px, sticky |
| Spacing defaults | toolbar gap `--sp-2`, card padding `--sp-3`, section gap `--sp-4`, page padding 16px sides and 12px top |
| Icons | 16px (14px in chips and badges, 20px only in empty states), 1.5px stroke |
| Chips and badges | 20px high (citation chips 22px with a 24px hit area) |
| Dialogs and drawers | dialog 440px, 16px padding, 32px footer buttons (primary last); details drawer and Documents used panel `--panel-w` 340px |

**Never smaller:** chat answer text stays `--fs-16` at `--lh-read` within `--chat-w` (about 70 characters a line); the PDF opens at 100%; focus rings stay 2px and are never clipped; error and required text is at least 13px, never truncated, with an icon; pointer targets are at least 24px; `--text-3` and placeholders keep 4.5:1.

**Truncation:** a single-line cell or title truncates with an ellipsis and shows the full text in a tooltip and the accessible name; a failure reason or error never truncates.

## Themes

Light is required, dark is supported: `tokens.css` defines both under `[data-theme="light"]` and `[data-theme="dark"]`. The app sets `data-theme` on `<html>` from `prefers-color-scheme`; a theme switch in the user menu comes later. Check every new screen in both themes (`THEME=both`).

## Layout

- **Laptop only:** designed at 1440px, checked at 1280px, `body { min-width: 1024px }`. No phone or tablet breakpoints.
- **App shell:** a two-column grid, left nav (`--nav-w`, collapsible to `--nav-w-collapsed`, `--surface`, right border) and a scrolling `<main id="main-content">`. Pages sit in a centered column of `--page-w` with 16px side and 12px top padding (a route sets `handle: { wide: true }` for the fluid `--page-w-wide`); chat uses `--chat-w`.
- **Page header:** one 40px row: h1 (`--fs-20`, sans), a short count or context in `--text-2` `--fs-13` on the same line, an info button whose tooltip holds any longer description, and the primary action on the right. Nothing wraps under the h1.
- **Toolbar:** one 36px row under the header: tabs with inline counts on the left, unlabelled compact filters (each with an `aria-label`; dates in one popover), a status chip that doubles as a filter (e.g. "1 needs subjects"), and the result count on the right.
- **Notices:** an inline notice is one 32px row (icon, one sentence, a link or small button) in the toolbar area; only errors and blocking states use a full-width banner. A `neutral` banner (`--surface-2` fill, `--border` outline, `--text-2` icon) marks a read-only state, such as an archived conversation.
- **Left nav,** 32px items in groups separated by a hairline (no uppercase group labels): Library (home), Chat (starts a new conversation) | Conversations (with the 3 most recent conversations as a sub-list), Notes | Subjects, Usage. Later releases slot in without reordering: Research map after Library (R2), Quizzes and Reports after Notes (R3); they are not rendered in Release 1. A chevron in the top brand row (a 40px row level with the chat header, right of the logo; below the logo on the rail) collapses the nav to a 56px icon rail (names in tooltips and `aria-label`); the choice is remembered. The current item has `aria-current="page"` (`--accent-soft` fill, `--accent-text`). Library shows a count badge (`--attn-soft` / `--attn`) for documents needing the learner's action. The user menu is one 36px row at the bottom: avatar initials, name, and a menu with Sign out.
- **Upload tray:** fixed bottom right (`--tray-w`), on every screen, non-blocking.
- **Landing page** (`/`): public, outside the app shell, centered `--page-w` column with header, hero, how it works, trust points, closing, footer.

## Components

Shared components live in `web/src/components/`, one folder each (`Button/Button.tsx` + `Button.module.css`); features compose them and keep only feature-specific styles. Build a component when a ticket first needs it, matching the prototype class it replaces:

| Component | Prototype | Notes |
|---|---|---|
| `AppShell`, `SideNav`, `UserMenu` | `.app`, `.sidenav`, `.nav-link`, `.user-btn`, `.user-menu` | routes come from one nav config |
| `PageHeader` | `.page-head` | |
| `Button`, `IconButton` | `.btn-primary` / `-secondary` / `-ghost` / `-quiet`, `-sm` / `-lg`; `.icon-btn` | one primary button per view; an icon button always has `aria-label` |
| `EmptyState` | `.empty` | icon, h2, one sentence, actions, optional `note` below the actions |
| `StateBadge` | `.state-*` | see Document states |
| `SubjectChip` | `.schip` | the one chip for subjects everywhere (Library, picker, lists; never in the chat header), learner's subject name, stable hue per subject |
| `FilterBar` | `.filter-bar` | built (Library): `role="search"` with a label, labelled fields (labels visually hidden in the compact toolbar; see Layout → Toolbar), live count, Clear filters shown only while a filter is set; `noun` reuses it for conversations and notes |
| `Tabs` | `.tabs` | built (Library): `role="tablist"` selector with roving tabindex and arrow/Home/End keys, optional count pill; no panels, the page's list is the panel |
| `RowMenu` | `.row-menu` | built (Library): a "More" icon button opening a `role="menu"` of icon + label items (first item focused, arrows move, Escape returns focus, blur closes) |
| `SidePanel` | `.side-panel` | built (document details): a right-hand modal drawer of `--panel-w`, kicker and badge header, close button, scrolling body, footer; focus moves in, Tab stays in, Escape closes, focus goes back |
| `Banner`, `Toast`, `Dialog`, `UploadTray`, `Citation`, `SystemNotice` | `.banner-*`, `.toast`, `.dialog`, `.tray`, `.cite`, `.notice` | built with the story that first shows them |

Icons: one outline family at 1.5px stroke, `lucide-react` with `strokeWidth={1.5}`, 16px by default (see Density), `aria-hidden` unless the icon is the only label.

## Document states

One visual language everywhere (Library row, details, upload tray). Color is always paired with a label and an icon.

| State | Look | Label |
|---|---|---|
| uploading, processing | `--surface-2` / `--text-2`, spinner | "Uploading" / "Processing" |
| needs action (choose subjects) | `--attn-soft` / `--attn` | "Choose subjects" |
| ready | `--success-soft` / `--success` | "Ready" |
| failed | `--danger-soft` / `--danger`, reason beneath | "Failed" |
| archived | `--surface-2` / `--text-2`, dashed border | "Archived" |

## Chat

The tutor's words, the learner's words, quoted document text, and system notices (e.g. "Started from note") each look different: quoted and cited material is set apart from the tutor's prose, and notices are centered dashed pills (the maximum warning uses `--info-soft`). Citations show the document's display title and page, or "page unavailable": one compact **Sources** line of 22px chips under each answer ("*Short title* · p. 3", full title in the tooltip and accessible name), each opening the document viewer. Helpful / Not helpful are two 28px icon buttons at the end of that line (`aria-label`, `aria-pressed`, visible tooltip). Each `[n]` in the answer's text is also a link to its source: `--accent-text`, underlined, a `:focus-visible` ring, `--accent-soft` and `aria-current` while its passage is shown, and the accessible name and tooltip "Source 2: *title*, p. 3". `[1, 2]` and `[1–3]` link each number shown. A number with no source in that answer stays text, as does a deleted document's marker (tooltip "Deleted document"); markers stay text while the answer streams and while Show citations is off. Markers sit inside a sentence, so the 24px target minimum doesn't apply to them (WCAG 2.5.8 inline exception). Quoted passages are a 13px block with a 2px left rule. **Chat layout (Q60).** The chat body has two panes:
- **Conversation panel** (left, `--chat-panel-w`, `--surface`, right border), toggled by a button at the left of the chat header (`aria-expanded`, `aria-controls`; the choice is remembered). Sections: **Documents** (32px rows: icon, title, page count, "Archived" / "Deleted" badge, a remove button on hover and focus; "Add documents" opens a searchable picker; the switch "Only search these documents" sits under the list, and when it is on the composer shows "Searching *N* documents"), **Lesson Note** (the conversation's note: open it, or "Summarize lesson" / "Update lesson note"), and **Actions** (Show citations switch, Archive conversation).
- **Conversation** (right): the messages in a column up to `--chat-w`, the composer, and the status line.

The chat header is one 40px row with only the panel toggle (a sidebar icon; tooltip and accessible name "Hide panel" / "Show panel", `aria-expanded`), the **editable title**: click it, or the pencil shown on hover and focus, to edit inline (Enter or blur saves, Esc cancels, 1–120 characters, an error under the field when empty), and **New conversation** at the row's right end (a small quiet button: pen-on-square icon and the label; the title truncates first). New conversation goes to an empty `/chat` like the Chat nav item and moves focus to the question box; it isn't shown on an empty new conversation. Every question after the first is asked in the same conversation and adds a turn under the history. No overflow menu (Q62). The panel toggle shares the top 40px row's alignment with the nav's chevron; the two use different icons so they are not confused.

**Scrolling.** The messages scroll like a chat. Asking scrolls the new question into view at the bottom. While an answer streams, the pane follows the new text only when the learner is at the bottom (within 40px); scrolling up stops the follow, and scrolling back to the bottom resumes it. While they are away from the bottom, a small **Jump to latest** pill (secondary small button with a down arrow, centred above the composer) scrolls to the newest turn and moves focus to the question box (to the newest turn while an answer streams); it hides at the bottom. Reopening a conversation lands on its newest turn, with every earlier turn above it (no "load earlier" paging in Release 1). While the learner reads earlier turns the messages stay where they were, even when a document opens or closes beside the conversation; at the bottom the newest text stays in view. Scrolling is instant under `prefers-reduced-motion`. Only the newest turn's answer region is `aria-live`.

**Split view.** One click on a document in the panel, on a Sources chip, or on an answer's `[n]` marker opens the document **beside the conversation**: the conversation keeps at least `--chat-min-w`, the document pane takes the rest, the conversation panel collapses and the app nav drops to its rail while the split is open (both re-openable). The pane has one 40px toolbar (title, "p. 3 / 33", zoom, **Open in dialog**, Close) and is a labelled region, not a modal: focus moves to its title on open; Esc or Close returns focus to the chip, marker, or row that opened it; the chip and markers whose passage is shown stay highlighted in the conversation. The viewer shows one page at a time. Previous/Next and PageUp/PageDown turn the page; so does **flip at the edge**: scrolling on past a page's bottom opens the next page at its top, and past its top opens the previous page at its bottom. It takes a deliberate extra scroll (wheel, trackpad, or touch) that starts at the edge, so the scroll that reaches the edge, trackpad momentum, and the scroll to a cited passage never turn the page, and one gesture turns at most one page; a page that fits the pane turns on one gesture. Nothing happens past the first or last page. Another chip, marker, or row swaps the document in place. A citation opens at its page with the passage highlighted: a soft accent fill over its lines, a 2px marker beside them, and a "Cited passage" label (fixed colors, since the page stays white); if the passage can't be found, the page opens with "Couldn't highlight the passage on this page." The page's text can be selected and copied: a transparent text layer lies over the drawn page, and the selection shows in a fixed blue (`rgb(0 0 255 / 0.25)`), never the accent, so it can't be mistaken for the cited passage. Outside chat (Library, details) the viewer is an overlay of `--viewer-w`. **Open in dialog** (an icon button with a label in its tooltip) opens the same document at the same page and highlight in that overlay, with a details strip (authors, year, subjects, pages) under its toolbar; closing it returns to the split view with focus on the button.

## Accessibility

WCAG 2.2 AA: pointer targets of at least 24px (links inside a sentence, such as an answer's citation markers, excepted), AA contrast in both themes, everything reachable and operable by keyboard, visible `:focus-visible` outlines, labelled controls. Announce processing-state changes and upload results through one polite live region; announce a streamed answer once when it completes, never word by word. The drop zone always has a keyboard "Upload" button beside it.

## Copy

Quoted text in the brief and in a ticket's acceptance criteria is required wording: use it verbatim. Use `CONTEXT.md` terms in code; UI copy may say "conversation" for a thread.
