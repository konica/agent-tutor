# DESIGN.md

How the web app looks and how to build its UI. Read this before writing anything in `web/src/`. The process for turning a ticket's mockup states into code (rendering states, reading the prototype at a round's tag) is in `AGENTS.md` → Design inputs; this file covers what the result must look like.

## Sources

| Need | Read |
|---|---|
| Screens, required wording, accessibility rules | `sdd/design/brief.md` (§6 screens, §10 visual rules) |
| What a state looks like | `make design-shots ROUND=v0.4 STATES="<ids>" THEME=both` (the round in the ticket's `## Design` section); ids in `sdd/design/states.json` |
| Token values | `web/src/styles/tokens.css` (ported from `sdd/design/prototype/styles.css` and `v03.css` at tag `design-v0.3`; round v0.4 added no tokens) |
| Design decisions and open questions | PRD v2.7 (Q38–Q43) and brief v0.4 (§0, Feedback log). The designer's round 3 questions E1–E10 are open; the ticket's `## Design` section says which apply. |

The brand is Smart Tutor's own (`smart-tutor-ds`, light and dark). The Open Design project has the Cisco design system switched on, but the owner chose the own brand instead (2026-10-02, `sdd/design/prototype/history/`); follow the accepted round's tokens, not Cisco.

## Tokens

Every color, size, space, radius, shadow, and duration in feature code is a `var(--…)` from `tokens.css`. A value the tokens lack goes into `tokens.css` (both themes) first, then gets used.

| Role | Tokens |
|---|---|
| Page and surfaces | `--bg` (page), `--surface` (cards, nav, tables), `--surface-2` / `--surface-3` (hover, headers, quiet fills) |
| Text | `--text`, `--text-2` (secondary), `--text-3` (disabled, placeholders) |
| Lines | `--border`, `--border-strong` (inputs, secondary buttons, dashed empty states) |
| Brand and actions | `--accent` (primary button fill), `--accent-hover`, `--accent-soft` (selected nav item, selected row), `--accent-text` (links, ghost buttons), `--on-accent` |
| Status | `--success`, `--warn`, `--danger`, `--info`, `--attn` (needs the learner's action), each with a `-soft` background |
| Subjects | `--subj-*` hues, used only through the subject chip |
| Focus | `--focus` (2px outline, 2px offset, on `:focus-visible`) |
| Type | `--font-display` (serif: h1–h3, brand word), `--font-body` (system UI), `--font-mono` (numbers, ids, token counts; tabular figures); sizes `--fs-12` … `--fs-40`; `--lh-body` 1.55, `--lh-head` 1.2 |
| Space and shape | `--sp-1` (4px) … `--sp-16` (64px); `--r-sm` 6px, `--r-md` 10px, `--r-pill` |
| Motion | `--dur-fast`, `--dur-base`, `--ease-out`; everything stops under `prefers-reduced-motion: reduce` |
| Layout | `--nav-w` 240px, `--page-w` 1120px, `--chat-w` 760px, `--panel-w` 480px, `--tray-w` 384px |

The prototype's `--chrome-*` tokens, `.rb-*` classes, and `od-*` layout primitives belong to the review tool, not the product: leave them out.

## Themes

Light is required, dark is supported: `tokens.css` defines both under `[data-theme="light"]` and `[data-theme="dark"]`. The app sets `data-theme` on `<html>` from `prefers-color-scheme`; a theme switch in the user menu comes later. Check every new screen in both themes (`THEME=both`).

## Layout

- **Laptop only:** designed at 1440px, checked at 1280px, `body { min-width: 1024px }`. No phone or tablet breakpoints.
- **App shell:** a two-column grid, left nav (`--nav-w`, `--surface`, right border) and a scrolling `<main id="main-content">`. Pages sit in a centered column of `--page-w` with `--sp-8` padding; chat uses `--chat-w`.
- **Page header:** h1 at `--fs-32` in the display font, an optional one-line description in `--text-2` (max 64ch), and the page's primary action on the right.
- **Left nav,** in this order: Library (home), Chat (starts a new conversation), Conversations, Notes, Subjects, Usage, Settings. Later releases slot in without reordering: Research map after Library (R2), Quizzes and Reports after Notes (R3); they are not rendered in Release 1. The current item has `aria-current="page"` (`--accent-soft` fill, `--accent-text`). Library shows a count badge (`--attn-soft` / `--attn`) for documents needing the learner's action. The user menu sits at the bottom: avatar initials, name, and Sign out.
- **Upload tray:** fixed bottom right (`--tray-w`), on every screen, non-blocking.

## Components

Shared components live in `web/src/components/`, one folder each (`Button/Button.tsx` + `Button.module.css`); features compose them and keep only feature-specific styles. Build a component when a ticket first needs it, matching the prototype class it replaces:

| Component | Prototype | Notes |
|---|---|---|
| `AppShell`, `SideNav`, `UserMenu` | `.app`, `.sidenav`, `.nav-link`, `.user-btn`, `.user-menu` | routes come from one nav config |
| `PageHeader` | `.page-head` | |
| `Button`, `IconButton` | `.btn-primary` / `-secondary` / `-ghost` / `-quiet`, `-sm` / `-lg`; `.icon-btn` | one primary button per view; an icon button always has `aria-label` |
| `EmptyState` | `.empty` | icon, h2, one sentence, actions |
| `StateBadge` | `.state-*` | see Document states |
| `SubjectChip` | `.schip` | the one chip for subjects everywhere (Library, picker, chat header, lists), learner's subject name, stable hue per subject |
| `Banner`, `Toast`, `Dialog`, `SidePanel`, `Tabs`, `FilterBar`, `UploadTray`, `Citation`, `SystemNotice` | `.banner-*`, `.toast`, `.dialog`, `.side-panel`, `.tabs`, `.filter-bar`, `.tray`, `.cite`, `.notice` | built with the story that first shows them |

Icons: one outline family at 1.5px stroke, `lucide-react` with `strokeWidth={1.5}`, sized 16–20px, `aria-hidden` unless the icon is the only label.

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

The tutor's words, the learner's words, quoted document text, and system notices (subject added, maximum reached) each look different: quoted and cited material is set apart from the tutor's prose, and notices are centered dashed pills (the maximum warning uses `--info-soft`). Citations show the document's display title and page, or "page unavailable".

## Accessibility

WCAG 2.1 AA: AA contrast in both themes, everything reachable and operable by keyboard, visible `:focus-visible` outlines, labelled controls. Announce processing-state changes and upload results through one polite live region; announce a streamed answer once when it completes, never word by word. The drop zone always has a keyboard "Upload" button beside it.

## Copy

Quoted text in the brief and in a ticket's acceptance criteria is required wording: use it verbatim. Use `CONTEXT.md` terms in code; UI copy may say "conversation" for a thread.
