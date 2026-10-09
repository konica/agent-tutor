# Compact density Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the web app to the compact density of design round v0.10 (ticket #126): new tokens, a compact app shell with a collapsible nav, compact base components, and compact Library, subject picker and Chat screens.

**Architecture:** Tokens change once in `web/src/styles/tokens.css`; shared components in `web/src/components/` take the compact sizes; features only compose them. A global `[data-tip]` CSS tooltip (hover and `:focus-visible`) serves the page-header info button, the collapsed nav rail, and truncated text. The nav's collapsed state lives in `localStorage` behind a small hook.

**Tech Stack:** React 19 + TypeScript, CSS Modules, Vite, Vitest + Testing Library, lucide-react icons.

**Spec:** GitHub issue #126 (`gh issue view 126 --repo konica/agent-tutor`), `DESIGN.md` → Density / Layout / Components (already written for compact density), mockup round `design-v0.10` (`sdd/design/prototype/v03.css` lines 391–931 at that tag hold the compact rules: `git show design-v0.10:sdd/design/prototype/v03.css | sed -n 391,931p`).

## Global Constraints

- Every color, font size, space, radius, shadow and duration in CSS is a `var(--…)` from `tokens.css`; control heights, icon sizes and 1–2px borders may be literal px. A missing value goes into `tokens.css` first.
- No text below 12px (`--fs-12`); error text at least 13px, never truncated, with an icon; pointer targets at least 24px; focus ring 2px `--focus`, 2px offset, never clipped (no `overflow: hidden` on an ancestor that would cut a focused control's outline — use `outline-offset: -2px` inside clipped containers).
- Icons: lucide-react, `strokeWidth={1.5}`, 16px default, 14px in chips and badges, 20px only in empty states, `aria-hidden="true"` unless the only label.
- Every icon-only button has `aria-label`; when it also has a tooltip, `data-tip` holds the same text.
- App headings use `--font-body`; serif (`--font-display`) only for the brand word, the landing page, and the empty-state headline.
- Chat answers stay `--fs-16` at `--lh-read` (1.6) within `--chat-w` (720px).
- Landing page (`web/src/features/landing/`) is unchanged except that it inherits shared tokens; it keeps its serif and large type. Its CSS must keep working after `--fs-40` is removed (check `grep -rn "fs-40" web/src`).
- Required copy, verbatim: "Only upload documents you have the right to use."; "Upload your first document".
- Laptop only, `body { min-width: 1024px }`; no breakpoints.
- Out of scope (later stories own them; do not build): Active/Archived tabs (#108), row "More" menu items Archive/Delete/Details (#108, #109, #125), a per-row "Chat" action (#132), the chat conversation panel and its Archive / Show citations actions (#122), clickable Sources chips and the viewer (#118, #124), Helpful / Not helpful (no feedback API), the token count (the stream carries none), a Library nav badge count, a `GET /threads` endpoint. The nav renders the recent-conversations slot from a prop that is empty until the conversations list exists.
- Keep `ChatPage.tsx` edits small: PR #144 (#121) rewrites the subject parts of that file; touch only the header class, the citations block and the composer.

## Review Focus

1. `localStorage` throws (private mode, blocked storage) → the nav still renders expanded and the toggle still works for the session. Test in Task 3.
2. A very long document title or chat question → one line with an ellipsis, the full text in `title`/tooltip and the accessible name, nothing wraps under the page title. Tests in Tasks 4 and 5.
3. A long failure reason → shown in full (wraps), never truncated, while other state hints truncate. Test in Task 4.
4. The "needs subjects" chip when the list is filtered by another state → hidden when no document needs subjects and it is not pressed; pressing it again clears the state filter. Test in Task 4.
5. The Uploaded popover: Escape closes it and returns focus to its button; the button shows the active style while a date is set. Test in Task 4.

---

### Task 1: Tokens, base styles, buttons and the tooltip rule

**Files:**
- Modify: `web/src/styles/tokens.css`, `web/src/styles/base.css`
- Modify: `web/src/components/Button/Button.module.css`, `web/src/components/Button/Button.tsx`
- Create: `web/src/components/Button/IconButton.tsx`
- Create: `web/src/styles/contrast.test.ts`
- Test: `web/src/components/Button/Button.test.tsx`

**Interfaces:**
- Produces: tokens `--fs-13`, `--lh-read`, `--sp-0`, `--r-lg`, `--nav-w-collapsed`, `--viewer-w`, `--control-h` (32px), `--control-h-sm` (28px); global `[data-tip]` tooltip rule; `IconButton({ label, icon, tip?, size?, ...buttonProps })` exported from `components/Button/IconButton.tsx` (28px square, `aria-label={label}`, `data-tip={tip === false ? undefined : label}`); `Button` sizes `sm` 28px, `md` 32px, `lg` 36px.

- [ ] **Step 1: Write the failing contrast test** `web/src/styles/contrast.test.ts`. It reads `tokens.css` with `fs.readFileSync(new URL("./tokens.css", import.meta.url), "utf8")`, parses the light block (`:root, [data-theme="light"] { … }`) and the dark block (`[data-theme="dark"] { … }`) into maps of `--name: #hex`, and asserts WCAG contrast ≥ 4.5 for `--text-2` and `--text-3` against `--bg`, `--surface`, and `--surface-2` in both themes (placeholders use `--text-3`). Also assert the new tokens exist: `--fs-13`, `--lh-read`, `--sp-0`, `--r-lg`, `--nav-w-collapsed`, `--viewer-w`, and that `--fs-40` is gone.

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");
const block = (selector: string) => {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2]!.trim()]));
};
const light = block(':root, [data-theme="light"]');
const dark = { ...light, ...block('[data-theme="dark"]') };

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

describe("tokens", () => {
  it.each([["light", light], ["dark", dark]] as const)("%s theme keeps 4.5:1 for secondary text and placeholders", (_, theme) => {
    for (const fg of ["--text-2", "--text-3"]) for (const bg of ["--bg", "--surface", "--surface-2"]) expect(ratio(theme[fg]!, theme[bg]!), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });

  it("defines the compact tokens", () => {
    for (const name of ["--fs-13", "--lh-read", "--sp-0", "--r-lg", "--nav-w-collapsed", "--viewer-w"]) expect(light[name], name).toBeDefined();
    expect(light["--fs-40"]).toBeUndefined();
  });
});
```

- [ ] **Step 2: Run it** — `cd web && npx vitest run src/styles/contrast.test.ts` — expected FAIL on the missing tokens (contrast may already pass).

- [ ] **Step 3: Change tokens** in the light block (dark inherits non-colour tokens):
  - `--fs-12: 12px; --fs-13: 13px; --fs-14: 14px; …` and drop `--fs-40`.
  - `--lh-body: 1.45; --lh-read: 1.6; --lh-head: 1.25;`
  - `--sp-0: 2px;` before `--sp-1`.
  - `--r-sm: 4px; --r-md: 6px; --r-lg: 8px; --r-pill: 999px;`
  - `--control-h: 32px; --control-h-sm: 28px;` `--nav-w: 208px; --nav-w-collapsed: 56px;` `--chat-w: 720px;` `--page-w: 1200px;` `--page-w-wide: 1360px;` (the shell caps it with `min(var(--page-w-wide), 100%)`, which makes it fluid) `--panel-w: 340px;` `--tray-w: 320px;` `--viewer-w: min(960px, 100% - 64px);` `--filter-field-w: 160px` stays.
  - Update the header comment: "…tag design-v0.3; compact density from design-v0.10 (DESIGN.md → Density)."
  - If the contrast test fails for a colour, darken (light) or lighten (dark) `--text-3` minimally and note it in the commit body.

- [ ] **Step 4: Base styles** in `base.css`: `body { font-size: var(--fs-14); }`; `h1, h2, h3 { font-family: var(--font-body); font-weight: 650; }` (the landing page and EmptyState set the serif explicitly — check `LandingPage.module.css` and `EmptyState.module.css` set `font-family: var(--font-display)` on their headings; add it where missing so the landing page looks unchanged); add the tooltip rule copied from the prototype (v03.css lines 5–13 at the tag):

```css
/* Tooltips: [data-tip] shows on hover and keyboard focus; the accessible name carries the same text (DESIGN.md → Density). */
[data-tip] { position: relative; }
[data-tip]:hover::after, [data-tip]:focus-visible::after {
  content: attr(data-tip); position: absolute; z-index: 80; left: 50%; top: calc(100% + 6px); transform: translateX(-50%);
  width: max-content; max-width: 320px; padding: 3px 8px; border-radius: var(--r-sm);
  background: var(--text); color: var(--bg); box-shadow: var(--shadow-sm);
  font-family: var(--font-body); font-size: var(--fs-12); font-weight: 500; line-height: 1.4; letter-spacing: 0;
  text-transform: none; text-align: left; white-space: normal; pointer-events: none;
}
```

  Also `input::placeholder, textarea::placeholder { color: var(--text-3); }`.

- [ ] **Step 5: Write failing Button tests** (append to `Button.test.tsx`):

```tsx
it("labels an icon button and shows the same text as its tooltip", () => {
  render(<IconButton label="Collapse navigation" icon={ChevronLeft} />);
  const button = screen.getByRole("button", { name: "Collapse navigation" });
  expect(button).toHaveAttribute("data-tip", "Collapse navigation");
  expect(button).toHaveAttribute("type", "button");
});

it("can drop the tooltip when visible text already names the action", () => {
  render(<IconButton label="Close" icon={X} tip={false} />);
  expect(screen.getByRole("button", { name: "Close" })).not.toHaveAttribute("data-tip");
});
```

- [ ] **Step 6: Run** — FAIL (no IconButton).

- [ ] **Step 7: Implement** `IconButton.tsx`:

```tsx
import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes } from "react";

import styles from "./Button.module.css";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { label: string; icon: LucideIcon; tip?: boolean };

// A 28px icon-only button; its label is the accessible name and, unless tip is false, the tooltip (DESIGN.md → Components).
export function IconButton({ label, icon: Icon, tip = true, className, type = "button", ...rest }: Props) {
  return (
    <button type={type} className={[styles.iconButton, className].filter(Boolean).join(" ")} aria-label={label} data-tip={tip ? label : undefined} {...rest}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
    </button>
  );
}
```

  `Button.module.css` (prototype v03.css lines 105–110): `.button { gap: 6px; font-size: var(--fs-14); }`, `.sm { min-height: var(--control-h-sm); padding: 0 10px; font-size: var(--fs-13); }`, `.md { min-height: var(--control-h); padding: 0 var(--sp-3); }`, `.lg { min-height: 36px; padding: 0 var(--sp-4); font-size: var(--fs-14); }`, and

```css
.iconButton {
  display: inline-grid; place-items: center; width: 28px; height: 28px; flex: none; padding: 0;
  border: 1px solid transparent; border-radius: var(--r-sm); background: transparent; color: var(--text-2);
}
.iconButton:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
```

- [ ] **Step 8: Replace `--fs-40` users.** `ChatPage.module.css` `.welcomeTitle` → `font-family: var(--font-display); font-size: var(--fs-24);` (the conversation's empty-state headline). `LandingPage.module.css` `.closeTitle` → `var(--fs-32)` (DESIGN.md lists no 40px size). Give the landing page its serif back after the base h1–h3 rule turns sans: in `LandingPage.module.css` add `.page :is(h1, h2, h3) { font-family: var(--font-display); font-weight: 600; letter-spacing: -.01em; }` using the landing's root class (check the class name in `LandingPage.tsx`). Then `cd web && npx vitest run src/components/Button src/styles && npm run build` — PASS.

- [ ] **Step 9: Commit** — `git add -A web/src && git commit -m "Move tokens, base styles and buttons to compact density"` (body: why — #126, owner found UI wasteful of space).

### Task 2: Compact shared components

**Files:**
- Modify: `web/src/components/PageHeader/PageHeader.tsx`, `PageHeader.module.css`
- Create: `web/src/components/PageHeader/PageHeader.test.tsx`
- Modify: `Banner/Banner.tsx`, `Banner.module.css`; Create `Banner/Banner.test.tsx`
- Modify: `StateBadge.module.css`, `SubjectChip.module.css` (+ `SubjectChip.tsx` size doc comment), `Dialog.module.css`, `Dialog.tsx` (close button → `IconButton`), `EmptyState.module.css`, `UploadTray.module.css`, `FilterBar.tsx`, `FilterBar.module.css`
- Tests: existing tests in those folders keep passing; update only assertions that encode old sizes.

**Interfaces:**
- Consumes: `IconButton` (Task 1), tokens.
- Produces:
  - `PageHeader({ title, count?, description?, actions?, titleClassName? })` — one 40px row: `h1` (20px, 650, sans, `white-space: nowrap; overflow: hidden; text-overflow: ellipsis`, `title={title}` attribute so the full text shows on hover), then `count` (`<span>` `--fs-13` `--text-2`), then, if `description`, an info button `<button type="button" className={styles.info} aria-label={`About ${title}`} data-tip={description}>` with lucide `Info` 16px, then `actions` pushed right (`margin-left: auto`). The `below` prop is removed (nothing may wrap under the h1); in the same commit drop ChatPage's `below={…}` subject chips (conversations have no subjects, PRD v2.21; PR #144 removes the rest).
  - `Banner({ variant: "success" | "info" | "attn" | "danger", title?, children, inline? })` — `inline` renders one 32px row (`min-height: 32px; padding: 2px 4px 2px 10px; font-size: var(--fs-13)`; icon 16px) with title and children on the same line; non-inline keeps the block banner at `--fs-13`, padding `--sp-2 --sp-3`. Icons per variant: success `CircleCheck`, info `Info`, attn `CircleAlert`, danger `CircleAlert`.
  - `FilterBar` with a `compact` look always: one row, labels visually hidden (`FilterField` label gets `className="visually-hidden"`), controls 28px (`--control-h-sm`) `--fs-13`, no card background or border, `gap: var(--sp-2)`; the count right-aligned (`--fs-13`). Keep the `role="search"` landmark and the Clear filters button.

- [ ] **Step 1: Write failing PageHeader tests** (`PageHeader.test.tsx`):

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PageHeader } from "./PageHeader";

describe("PageHeader", () => {
  it("puts the count, the info button and the actions on the title's row", () => {
    render(<PageHeader title="Library" count="8 documents" description="Your documents." actions={<button type="button">Upload</button>} />);
    expect(screen.getByRole("heading", { level: 1, name: "Library" })).toBeVisible();
    expect(screen.getByText("8 documents")).toBeVisible();
    const info = screen.getByRole("button", { name: "About Library" });
    expect(info).toHaveAttribute("data-tip", "Your documents.");
    expect(screen.getByRole("button", { name: "Upload" })).toBeVisible();
  });

  it("keeps a long title on one line with the full text on hover", () => {
    const long = "How does ReAct combine reasoning and acting when the observation contradicts the plan?";
    render(<PageHeader title={long} />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveAttribute("title", long);
  });

  it("shows no info button without a description", () => {
    render(<PageHeader title="Chat" />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
```

- [ ] **Step 2: Banner test** (`Banner.test.tsx`): renders `<Banner variant="info" inline>Two documents are processing.</Banner>` and asserts the text is visible and the root has the inline class (`container.firstChild` has class matching `/inline/`); renders `<Banner variant="success" title="Saved">Ready</Banner>` and asserts "Saved" is visible.

- [ ] **Step 3: Run** — FAIL.

- [ ] **Step 4: Implement** PageHeader and Banner as specified above. CSS values (prototype v03.css lines 53–61, 89–101, 125–138):
  - `PageHeader.module.css`: `.header { display: flex; align-items: center; gap: var(--sp-2); min-height: 40px; margin: 0 0 var(--sp-2); }` `.title { min-width: 0; font-size: var(--fs-20); font-weight: 650; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }` `.count { font-size: var(--fs-13); color: var(--text-2); white-space: nowrap; }` `.info { width: 24px; height: 24px; display: inline-grid; place-items: center; flex: none; padding: 0; background: transparent; border: 0; border-radius: 50%; color: var(--text-2); }` `.info:hover { background: var(--surface-2); color: var(--text); }` `.info[data-tip]::after { left: 0; transform: none; }` `.actions { display: flex; align-items: center; gap: var(--sp-2); flex: none; margin-left: auto; }`.
  - `StateBadge`: `min-height: 20px; gap: 4px; padding: 0 var(--sp-2); font-size: var(--fs-12);` icon 14px.
  - `SubjectChip`: default and `sm` → `min-height: 20px; gap: 5px; --pad: var(--sp-2); font-size: var(--fs-12);` dot 6px; `button.chip { min-height: 28px; font-size: var(--fs-13); --pad: 10px; }`; `lg` (picker) → `min-height: 32px; --pad: 10px;`. Update the size comment: "lg is the picker's 32px size".
  - `Dialog`: `.dialog { width: min(440px, 100%); border-radius: var(--r-lg); }` `.wide { width: min(560px, 100%); }` header padding `var(--sp-4) var(--sp-4) 0`, `.title { font-size: var(--fs-18); }`, kicker unchanged, body `padding: var(--sp-3) var(--sp-4) var(--sp-4); font-size: var(--fs-14);`, footer `gap: var(--sp-2); padding: var(--sp-3) var(--sp-4);`. Close button → `<IconButton label="Close" icon={X} tip={false} onClick={onClose} />` (keep `aria-label="Close"`; Dialog tests use it). Footer buttons are the default `md` (32px) — callers already use md.
  - `EmptyState`: padding `var(--sp-12) var(--sp-6)`; icon wrap 48px (default) / 48px (dropzone), icon 20px; `.title` keeps `font-family: var(--font-display); font-weight: 600;` with `--fs-20` (default) and `--fs-24` (dropzone); `.text` and `.note` `--fs-13`; actions `gap: var(--sp-2)`.
  - `UploadTray`: width already via `--tray-w`; head padding `var(--sp-1) var(--sp-1) var(--sp-1) var(--sp-3)`, icon buttons 28px, items `padding: var(--sp-2) var(--sp-3)`, name `--fs-13`, status `--fs-12`, icon 16px, `grid-template-columns: 16px minmax(0, 1fr); gap: var(--sp-2)`; `--r-lg` radius.
  - `FilterBar.module.css`: `.bar { display: flex; align-items: center; gap: var(--sp-2); flex: 1 1 0; min-width: 0; }` `.field select, .field input { min-height: var(--control-h-sm); height: var(--control-h-sm); padding: 0 var(--sp-2); font-size: var(--fs-13); border-radius: var(--r-sm); }` `.field select { max-width: 180px; }` `.summary { margin-left: auto; gap: var(--sp-2); font-size: var(--fs-13); min-height: var(--control-h-sm); }`. Labels: `<label htmlFor={id} className="visually-hidden">`. Remove `.range`/`.dash` only if no longer used after Task 4 — leave them for now.

- [ ] **Step 5: Run** `cd web && npx vitest run src/components` — PASS; fix any existing test that asserted removed `below`.

- [ ] **Step 6: Commit** — "Compact the shared components".

### Task 3: App shell — compact, grouped, collapsible nav

**Files:**
- Modify: `web/src/app/nav.ts`, `web/src/components/SideNav/SideNav.tsx`, `SideNav.module.css`, `web/src/components/AppShell/AppShell.tsx`, `AppShell.module.css`, `web/src/components/UserMenu/UserMenu.tsx`, `UserMenu.module.css`, `web/src/components/BrandMark/BrandMark.module.css`
- Create: `web/src/components/SideNav/useNavCollapsed.ts`, `web/src/components/SideNav/SideNav.test.tsx`
- Test: `web/src/app/routes.test.tsx` (keep passing)

**Interfaces:**
- Produces:
  - `nav.ts`: `NavItem` gains `group: 0 | 1 | 2` — Library 0, Chat 0, Conversations 1, Notes 1, Subjects 2, Usage 2. `NAV` order unchanged.
  - `export type RecentConversation = { id: string; title: string; path: string }` in `nav.ts`.
  - `useNavCollapsed(): [boolean, () => void]` — reads `localStorage.getItem("smart-tutor.nav-collapsed") === "1"` once (try/catch → false), toggle writes `"1"`/`"0"` (try/catch, ignore failures).
  - `SideNav({ collapsed, onToggle, recent = [] }: { collapsed: boolean; onToggle: () => void; recent?: RecentConversation[] })`.
  - `UserMenu` gains `compact?: boolean` (collapsed rail: shows only the avatar; the button's accessible name stays the user's name via `aria-label={name}` and `data-tip={name}`).
  - `AppShell` owns `const [collapsed, toggle] = useNavCollapsed();`, adds `styles.collapsed` to `.app`, and passes `recent={[]}` (comment: "filled when the conversations list exists (US-5)").

- [ ] **Step 1: Write failing SideNav tests** (`SideNav.test.tsx`). Render inside `MemoryRouter` (`react-router`) and a session — check how `routes.test.tsx` provides `useSession` (it renders through `SessionProvider` or a fake); if `SideNav` needs a session, wrap with the same helper used there, or export `SessionContext`-free props. Tests:

```tsx
it("groups the items and marks the current page", () => {
  renderNav({ path: "/library" });
  const nav = screen.getByRole("navigation", { name: "Main" });
  expect(within(nav).getByRole("link", { name: "Library" })).toHaveAttribute("aria-current", "page");
  expect(nav.querySelectorAll("hr")).toHaveLength(2);
});

it("lists up to three recent conversations under Conversations", () => {
  renderNav({ recent: [1, 2, 3, 4].map((n) => ({ id: `t${n}`, title: `Question ${n}`, path: `/conversations/t${n}` })) });
  const list = screen.getByRole("list", { name: "Recent conversations" });
  expect(within(list).getAllByRole("link")).toHaveLength(3);
});

it("collapses to the icon rail with names as accessible names and tooltips", async () => {
  const onToggle = vi.fn();
  renderNav({ collapsed: true, onToggle });
  const chat = screen.getByRole("link", { name: "Chat" });
  expect(chat).toHaveAttribute("data-tip", "Chat");
  await userEvent.click(screen.getByRole("button", { name: "Expand navigation" }));
  expect(onToggle).toHaveBeenCalled();
});

it("hides the recent conversations on the rail", () => {
  renderNav({ collapsed: true, recent: [{ id: "t1", title: "Q", path: "/conversations/t1" }] });
  expect(screen.queryByRole("list", { name: "Recent conversations" })).toBeNull();
});
```

  And `useNavCollapsed` tests (same file or `useNavCollapsed.test.ts` with `renderHook`): starts expanded with empty storage; toggling writes `"1"` and a fresh hook reads collapsed (survives reload); when `localStorage.getItem`/`setItem` throw (`vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked"); })`) it starts expanded and toggling still flips the state.

  AppShell keyboard test (in `routes.test.tsx` or SideNav test with the real AppShell): Tab to "Collapse navigation", press Enter, the button is now named "Expand navigation", `localStorage.getItem("smart-tutor.nav-collapsed") === "1"`; clear `localStorage` in `afterEach`.

- [ ] **Step 2: Run** — FAIL.

- [ ] **Step 3: Implement.**

`useNavCollapsed.ts`:

```ts
import { useCallback, useState } from "react";

const KEY = "smart-tutor.nav-collapsed";

// The nav's rail choice survives a reload (DESIGN.md → Layout); blocked storage just forgets it.
export function useNavCollapsed(): [boolean, () => void] {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(KEY) === "1";
    } catch {
      return false;
    }
  });
  const toggle = useCallback(() => {
    setCollapsed((was) => {
      try {
        localStorage.setItem(KEY, was ? "0" : "1");
      } catch {
        // keep the choice for this visit only
      }
      return !was;
    });
  }, []);
  return [collapsed, toggle];
}
```

`SideNav.tsx` structure: brand link (on the rail, the word is hidden; the link keeps `aria-label="Smart Tutor, Library"`), then for each group a `<ul>` of items, separated by `<hr className={styles.hr} />`; each `NavLink` gets `aria-label={collapsed ? label : undefined}` and `data-tip={collapsed ? label : undefined}`, the label in `<span className={styles.text}>` (not rendered when collapsed). Under the Conversations item, when `!collapsed && recent.length`, `<ul className={styles.sub} aria-label="Recent conversations">` with `recent.slice(0, 3)` as `NavLink`s (`title={c.title}`, text truncated with ellipsis). A footer `<div className={styles.foot}>` with `<IconButton label={collapsed ? "Expand navigation" : "Collapse navigation"} icon={collapsed ? ChevronRight : ChevronLeft} aria-expanded={!collapsed} onClick={onToggle} className={styles.collapse} />` then `<UserMenu name={name} onSignOut={signOut} compact={collapsed} />`. Keep `aria-label="Main"`.

CSS (prototype v03.css lines 15–48): `.sidenav { display: flex; flex-direction: column; gap: var(--sp-0); padding: var(--sp-3) var(--sp-2) var(--sp-2); }` `.link { min-height: 32px; gap: 10px; padding: 0 var(--sp-2); font-size: var(--fs-14); position: relative; }` icon 16px; `.hr { border: 0; height: 1px; margin: var(--sp-2); background: var(--border); }` `.sub { list-style: none; margin: 0 0 var(--sp-1); padding: 0 0 0 34px; display: grid; }` `.sub a { display: block; min-height: 28px; line-height: 28px; padding: 0 var(--sp-2); border-radius: var(--r-sm); font-size: var(--fs-13); color: var(--text-2); text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }` `.foot { margin-top: auto; display: grid; gap: var(--sp-1); padding-top: var(--sp-2); border-top: 1px solid var(--border); }` `.collapse { justify-self: end; }`; collapsed (`.collapsed` on the nav root): `overflow: visible`, links `justify-content: center; padding: 0`, `.collapse { justify-self: center; }`, `[data-tip]::after { left: calc(100% + 10px); top: 50%; transform: translateY(-50%); }`, `.hr { margin: var(--sp-2) var(--sp-1); }`. The non-collapsed nav keeps `overflow-y: auto`. BrandMark in the nav: logo 24px, word `--fs-16` (pass a `className`/size via the SideNav CSS: `.brand svg { width: 24px; height: 24px; }`, `.brand span span { font-size: var(--fs-16) }` — or better give `BrandMark` a `size?: "sm" | "md"` prop; landing keeps `md`).

`AppShell.module.css`: `.app { grid-template-columns: var(--nav-w) minmax(0, 1fr); }` `.app.collapsed { grid-template-columns: var(--nav-w-collapsed) minmax(0, 1fr); }` `.page { max-width: var(--page-w); padding: 12px 16px 32px; }` `.wide { max-width: min(var(--page-w-wide), 100%); }`.

`UserMenu.module.css` (lines 34–38): `.foot { position: relative; }` (no margin-top/padding; SideNav's foot handles it) `.user { min-height: 36px; gap: var(--sp-2); padding: 0 var(--sp-2); border-radius: var(--r-sm); }` avatar 24px `--fs-12`, name `--fs-14` 600, `.menu { padding: var(--sp-1); border-radius: var(--r-lg); }` `.head { padding: var(--sp-2); margin-bottom: var(--sp-1); }` `.item { min-height: 32px; gap: var(--sp-2); padding: 0 var(--sp-2); font-size: var(--fs-13); }`. Compact: hide `.who` and the chevron, center the avatar, set `aria-label={name}` and `data-tip={name}` on the toggle; on the rail the menu opens to the right (`.compactMenu { left: calc(100% + var(--sp-2)); bottom: 0; right: auto; min-width: 184px; }`).

- [ ] **Step 4: Run** `cd web && npx vitest run src/components src/app` — PASS.

- [ ] **Step 5: Commit** — "Compact the app shell and let the nav collapse to a rail".

### Task 4: Library and subject picker

**Files:**
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.module.css`, `LibraryFilters.tsx`, `DocumentTable.tsx`, `DocumentTable.module.css`, `SubjectPicker.module.css`
- Create: `web/src/features/library/UploadedFilter.tsx`, `UploadedFilter.module.css`
- Tests: `LibraryPage.test.tsx`, `LibraryFilters.test.tsx`, `DocumentTable.test.tsx`, `SubjectPicker.test.tsx`

**Interfaces:**
- Consumes: `PageHeader({ title, count, description, actions })`, compact `FilterBar`, `Button size="sm"`, tokens, `[data-tip]`.
- Produces:
  - `LibraryFilters` props gain `needsSubjects: number` (count of `awaiting_subjects` documents in the loaded list).
  - `UploadedFilter({ from, to, onChange }: { from?: string; to?: string; onChange: (range: { uploaded_from?: string; uploaded_to?: string }) => void })`.

Layout (mockup `library-default@v0.10`):
- Header: `<PageHeader title="Library" count={documents ? `${n} ${n === 1 ? "document" : "documents"}` : undefined} description="Your documents. They're private to you, and the tutor answers only from them." actions={…} />`, where actions = `<p className={styles.rights}>Only upload documents you have the right to use.</p>` + the Upload button (md, primary). Show the count only when documents loaded and the list is unfiltered (when filtered, the toolbar count already says it). Actions render whenever documents are loaded and non-empty or filtered (as now).
- Toolbar: one 36px row with bottom hairline (`.toolbar { display: flex; align-items: center; gap: var(--sp-2); min-height: 36px; margin: 0 0 var(--sp-2); border-bottom: 1px solid var(--border); }`) holding `LibraryFilters`: Subject select (aria-label "Subject", option "All subjects"), `UploadedFilter`, State select (aria-label "State", option "All states"), the "*N* needs subjects" chip, then the count + Clear filters on the right.
- Notices (status, failed, rejected, already-in) move to 13px compact rows: `.status` `--fs-13`; `.error`/`.rejected`/`.already` padding `var(--sp-2) var(--sp-3)`, `--fs-13`, icons 16px, margin `0 0 var(--sp-2)`. Failure text stays untruncated.
- Empty card adds `<p>Only upload documents you have the right to use.</p>` after the limits line (brief §6 first run; mockup `library-empty`); its button stays `size="lg"` (36px).

- [ ] **Step 1: Failing tests.**

`LibraryFilters.test.tsx` (adapt setup to pass `needsSubjects`):

```tsx
it("filters by the needs-subjects chip and clears it on a second press", async () => {
  const onChange = vi.fn();
  renderFilters({ filters: {}, needsSubjects: 2, onChange });
  await userEvent.click(screen.getByRole("button", { name: "2 need subjects" }));
  expect(onChange).toHaveBeenLastCalledWith({ state: "awaiting_subjects" });
});

it("shows the chip pressed while the state filter is on, and pressing it again clears the filter", async () => {
  const onChange = vi.fn();
  renderFilters({ filters: { state: "awaiting_subjects" }, needsSubjects: 1, onChange });
  const chip = screen.getByRole("button", { name: "1 needs subjects" });
  expect(chip).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(chip);
  expect(onChange).toHaveBeenLastCalledWith({});
});

it("hides the chip when nothing needs subjects", () => {
  renderFilters({ filters: { state: "ready" }, needsSubjects: 0 });
  expect(screen.queryByRole("button", { name: /needs? subjects/ })).toBeNull();
});

it("keeps every filter labelled though the labels are hidden", () => {
  renderFilters({ filters: {}, needsSubjects: 0 });
  expect(screen.getByLabelText("Subject")).toBeInTheDocument();
  expect(screen.getByLabelText("State")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Uploaded" })).toHaveAttribute("aria-expanded", "false");
});
```

`UploadedFilter` tests (in `LibraryFilters.test.tsx`): clicking "Uploaded" opens a group with "From" and "To" date inputs (`getByLabelText("From")`), focus moves to "From"; typing a date calls `onChange({ uploaded_from: "2026-09-01" })`; Escape closes it and focus returns to the "Uploaded" button; with `from` set, the button's accessible name includes the range (assert `getByRole("button", { name: "Uploaded: from 2026-09-01" })`) and it has the active style class. Clicking outside (focus leaves the popover) closes it.

`DocumentTable.test.tsx`:

```tsx
it("keeps a row on one line: authors and year inline, the full title in the tooltip", () => {
  render(<DocumentTable documents={[doc({ title: "Toolformer: Language Models Can Teach Themselves to Use Tools", authors: ["Schick", "Dwivedi-Yu"], year: 2023 })]} onRetry={() => {}} retrying={new Set()} />);
  const title = screen.getByText("Toolformer: Language Models Can Teach Themselves to Use Tools");
  expect(title).toHaveAttribute("title", "Toolformer: Language Models Can Teach Themselves to Use Tools");
  expect(title.closest("td")).toHaveTextContent(/Schick/);
});

it("puts the processing hint on the badge line with the full hint as its tooltip", () => {
  render(<DocumentTable documents={[doc({ state: "processing" })]} onRetry={() => {}} retrying={new Set()} />);
  expect(screen.getByText("You can choose subjects when processing finishes.")).toHaveAttribute("title", "You can choose subjects when processing finishes.");
});

it("shows a failure reason in full", () => {
  const reason = "No text layer (scanned PDFs are not supported yet)";
  render(<DocumentTable documents={[doc({ state: "failed", failure_reason: reason, can_retry: true })]} onRetry={() => {}} retrying={new Set()} />);
  expect(screen.getByText(reason)).not.toHaveAttribute("title"); // not truncated, so no tooltip needed
});
```

  (Use or write the `doc()` factory the file already has; check its top.)

`LibraryPage.test.tsx`: assert the header shows "Only upload documents you have the right to use." beside Upload when documents exist, the empty card shows "Upload your first document" and the same sentence, and the count "3 documents" appears in the header for an unfiltered list. Update existing assertions that looked up filters by their old visible labels ("From", "To" now live in the popover — open it first) and the description paragraph (now a tooltip on "About Library").

- [ ] **Step 2: Run** `npx vitest run src/features/library` — FAIL.

- [ ] **Step 3: Implement `UploadedFilter.tsx`:**

```tsx
import { CalendarDays, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import styles from "./UploadedFilter.module.css";

type Range = { uploaded_from?: string; uploaded_to?: string };
type Props = { from?: string; to?: string; onChange: (range: Range) => void };

const describe = (from?: string, to?: string) => (from && to ? `${from} to ${to}` : from ? `from ${from}` : to ? `until ${to}` : "");

// The upload-date range in one popover, so the toolbar stays one row (DESIGN.md → Layout → Toolbar).
export function UploadedFilter({ from, to, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const range = describe(from, to);

  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || !open) return;
    e.stopPropagation();
    setOpen(false);
    button.current?.focus();
  };
  const onBlur = (e: FocusEvent) => {
    if (open && !root.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  return (
    <div className={styles.root} ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
      <button ref={button} type="button" className={range ? `${styles.button} ${styles.on}` : styles.button} aria-expanded={open} aria-controls={popId} aria-label={range ? `Uploaded: ${range}` : "Uploaded"} onClick={() => setOpen((v) => !v)}>
        <CalendarDays className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
        Uploaded
        <ChevronDown className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.pop} id={popId} role="group" aria-label="Upload dates">
          <label className={styles.field}>
            From
            <input ref={first} type="date" value={from ?? ""} max={to || undefined} onChange={(e) => onChange({ uploaded_from: e.target.value })} />
          </label>
          <label className={styles.field}>
            To
            <input type="date" value={to ?? ""} min={from || undefined} onChange={(e) => onChange({ uploaded_to: e.target.value })} />
          </label>
        </div>
      )}
    </div>
  );
}
```

CSS from prototype v03.css lines 73–81 (`.tb-btn`, `.tb-btn.on`, `.pop`, `.pop-field`, `.pop .input`) with 28px height, `--fs-13`, popover `--r-lg`, `--shadow-lg`, `z-index: 30`.

  `LibraryFilters`: replace the `FilterRange` block with `<UploadedFilter from={filters.uploaded_from} to={filters.uploaded_to} onChange={set} />`; selects get `aria-label` via their visually-hidden `FilterField` label; add after State:

```tsx
{(needsSubjects > 0 || filters.state === "awaiting_subjects") && (
  <button type="button" className={styles.chip} aria-pressed={filters.state === "awaiting_subjects"} onClick={() => set({ state: filters.state === "awaiting_subjects" ? undefined : "awaiting_subjects" })}>
    <Tag className={styles.chipIcon} strokeWidth={1.5} aria-hidden="true" />
    {needsSubjects === 1 ? "1 needs subjects" : `${needsSubjects} need subjects`}
  </button>
)}
```

  with a `LibraryFilters.module.css` holding the status-chip CSS (prototype lines 82–85: 24px high, `--attn-soft`/`--attn`, `--fs-12` 650, pressed = `box-shadow: inset 0 0 0 1px var(--attn)`). `LibraryPage` passes `needsSubjects={documents.filter((d) => d.state === "awaiting_subjects").length}` and wraps `LibraryFilters` in `<div className={styles.toolbar}>`.

  `DocumentTable` (prototype `library-default`): `table-layout: fixed`; columns Document (auto), Subjects 220px, State 260px, Uploaded 96px, actions 150px (`<colgroup>`). Header row 28px: `th { height: 28px; padding: 0 var(--sp-3); font-size: var(--fs-12); font-weight: 600; text-transform: none; letter-spacing: 0; position: sticky; top: 0; z-index: 1; }`. Rows: `td { height: 40px; padding: 0 var(--sp-3); }` (a failed row may grow because its reason wraps). Document cell: file icon 16px bare (no box), then `<span className={styles.title} title={doc.title}>` (600, `--fs-14`, ellipsis) and the byline inline `<span className={styles.byline}>` (`--fs-13`, `--text-2`, ellipsis), all in one `display: flex; align-items: center; gap: var(--sp-2); min-width: 0; white-space: nowrap` line. Subjects cell: `SubjectChip` (20px) for each subject, nowrap, overflow hidden; or "Not chosen yet" muted `--fs-13`. State cell: `display: flex; align-items: center; gap: var(--sp-2); white-space: nowrap;` badge then hint `<span className={styles.hint} title={hint}>` (`--fs-12`, ellipsis, `min-width: 0`); the attempt line joins the hint: "Attempt 2 of 3 · You can choose subjects when processing finishes." For failed: badge, then the reason on its own line, `display: block; white-space: normal; font-size: var(--fs-13); color: var(--danger)` with a `CircleAlert` 14px icon before it — never truncated (cell switches to `flex-direction: column; align-items: flex-start` for failed rows, padding `var(--sp-2) var(--sp-3)`). Uploaded: `--fs-12` `--text-2` tabular nums, shorter date format `day: "numeric", month: "short"` plus year only when not this year. Actions: `Button size="sm"` (28px), always visible. The `:target` row highlight stays; `tr:hover td { background: var(--surface-2); }` and the `awaiting_subjects` row gets `background: color-mix(in oklab, var(--attn-soft) 60%, var(--surface))` (mockup).

  `SubjectPicker.module.css` compact: `.doc` padding `var(--sp-3)`, `.title` body font 650 `--fs-16`, `.summary` `--fs-13` line-height 1.5, fieldset margin `var(--sp-4) 0 0`, legend/counter `--fs-13`, `.chips` gap `var(--sp-2)`, `.input` `min-height: var(--control-h); font-size: var(--fs-14);`, helper/notes/errors `--fs-13`, `.option` `--fs-13` min-height 32px. Run its tests unchanged.

- [ ] **Step 4: Run** `npx vitest run src/features/library` — PASS.

- [ ] **Step 5: Commit** — "Compact the Library toolbar, rows and subject picker".

### Task 5: Chat

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx` (header, citations block, composer only), `ChatPage.module.css`
- Test: `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `PageHeader` (no `below`), `IconButton`, tokens, `[data-tip]`.

Behavior (mockup `chat-answer-citations@v0.10`, ticket Chat bullets, minus the out-of-scope items):
- Header: `<PageHeader title={exchange.question} />` — the PageHeader's one-line ellipsis replaces `.clampedTitle`; the subject chips previously passed in `below` are dropped (conversations have no subjects, PRD v2.21). Before a question: `<PageHeader title="New conversation" />` with no description line. Header row 40px with a bottom hairline (`.column > header:first-child` styled via a wrapper class: wrap the header in `<div className={styles.head}>` with `border-bottom: 1px solid var(--border); margin-bottom: var(--sp-4)`).
- Welcome: `.welcomeTitle` → `font-family: var(--font-display); font-size: var(--fs-24)` (it is the conversation's empty-state headline); text `--fs-14`.
- Question bubble: `--fs-14`, padding `var(--sp-2) var(--sp-3)`, `--surface-2` background (mockup), `--r-lg`.
- Answer: `font-size: var(--fs-16); line-height: var(--lh-read);` no card border — plain prose (mockup), `max-width: var(--chat-w)`.
- Sources: replace the "Citations" section with one line:

```tsx
<div className={styles.sources}>
  <span className={styles.sourcesLabel} id={sourcesId}>Sources</span>
  <ul className={styles.sourceList} aria-labelledby={sourcesId}>
    {exchange.citations.map((c) => (
      <li key={c.chunk_id}>
        <span className={styles.source} title={formatCitation(c)}>
          <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
          <span className={styles.sourceMarker}>[{c.n}]</span>
          <span className={styles.sourceTitle}>{c.document_title}</span>
          <span>· {c.page === null ? "page unavailable" : `p. ${c.page}`}</span>
        </span>
      </li>
    ))}
  </ul>
</div>
```

  (`sourcesId` from `useId()`.) Chips 22px high, `--fs-12`, `--r-sm`, `1px solid var(--border-strong)`, `--surface`; `.sourceTitle { max-width: 24ch; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }`. They are not buttons until the viewer exists (#124). Keep each chip's text containing the full title (the ellipsis is visual only; `title` holds the full citation).
- Composer: one bordered box (`--r-lg`, `--border-strong`, `--surface`) holding a `textarea` with `rows={1}`, `min-height: 40px`, auto-growing via `field-sizing: content; max-height: 200px;`, `--fs-14`, and a 28px icon submit button inside on the right: `<IconButton type="submit" label="Ask" icon={ArrowUp} tip={false} disabled={!canAsk} className={styles.send} />` styled primary (`background: var(--accent); color: var(--on-accent)`; disabled `--surface-2`/`--text-3`). Under it one 12px line `.statusLine { display: flex; justify-content: space-between; gap: var(--sp-3); font-size: var(--fs-12); color: var(--text-2); margin-top: var(--sp-1); }` with the processing hint (clock icon 14px) on the left when `processing > 0` and "Enter to send · Shift + Enter for a new line" on the right. Composer sits at the bottom of the column: `.column { display: flex; flex-direction: column; min-height: calc(100dvh - 44px); }` and the form gets `margin-top: auto; padding-top: var(--sp-4); position: sticky; bottom: 0; background: var(--bg); padding-bottom: var(--sp-2);`.
- Thinking line and problem box: `--fs-13`; problem keeps a `CircleAlert` 16px icon and is never truncated.

- [ ] **Step 1: Failing tests** in `ChatPage.test.tsx` (reuse its `ask` fakes):
  - the header h1 holds the question with `title` = the question;
  - after an answer with citations `[{ n: 1, chunk_id: "c1", document_title: "ReAct: Synergizing Reasoning and Acting", page: 3 }]`, `screen.getByText("Sources")` is visible and the chip has `title="ReAct: Synergizing Reasoning and Acting, p. 3"`; a `page: null` citation shows "page unavailable";
  - the submit button is named "Ask" (existing tests use `name: "Ask"` — keep them passing);
  - the hint "Enter to send · Shift + Enter for a new line" is visible; with 2 processing documents "2 documents are still processing and can't be used yet." is visible.
  - Update assertions that looked for the "Citations" heading.

- [ ] **Step 2: Run** `npx vitest run src/features/chat` — FAIL.

- [ ] **Step 3: Implement** as above; remove now-unused CSS (`.clampedTitle`, `.citations*`, `.marker`, `.chips`, `.headerChips` only if unused — `.chips`/`.yourSubjects` are still used by the welcome's subject list until PR #144 lands, keep those).

- [ ] **Step 4: Run** `npx vitest run src/features/chat` — PASS.

- [ ] **Step 5: Commit** — "Compact the chat header, sources and composer".

### Task 6: Verify against the mockups and finish

**Files:**
- Modify: `DESIGN.md` only if the implementation had to differ (e.g. the Library tabs slot); `sdd/design/brief.md` Feedback log only for a mockup/PRD conflict.

- [ ] **Step 1:** `cd web && npm run build && npm test` — all pass.
- [ ] **Step 2:** Run the app and screenshot at 1440×900 in both themes: Library with the seed data (≥12 rows visible, nothing wraps under the title), Library with the nav collapsed, the chat with an answer, a dialog. If the full stack can't run, render the screens with Vite and a Playwright script that mocks the API (`page.route("**/documents*", …)`) and a fake session; compare with `.design-shots/v0.10/{library-default,chat-answer-citations,shell-nav-collapsed,library-delete-confirm}.{light,dark}.png`.
- [ ] **Step 3:** Fix visible differences that are in scope; list out-of-scope differences in the PR description.
- [ ] **Step 4:** Commit and open the PR closing #126.
