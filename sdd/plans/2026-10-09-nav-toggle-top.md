# Nav Toggle at the Top Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the left nav's collapse/expand chevron from the nav foot to a 40px brand row at the top of the nav, aligned with the chat header (issue #163).

**Architecture:** `SideNav` gets a `.head` row that wraps the brand link and the existing `IconButton`; the foot keeps only the `UserMenu`. CSS makes the head a 40px flex row (button right-aligned) when expanded, and a centered column (logo, then button) on the 56px rail. No state, hook, or prop changes.

**Tech Stack:** React 19 + TypeScript, CSS modules, Vitest + Testing Library, lucide-react.

**Spec:** issue #163 and design brief v0.11 §0 P8 (`sdd/design/brief.md`); mockup states `shell-nav-collapsed`, `library-default`, `chat-answer-citations` (`make design-shots STATES="shell-nav-collapsed,library-default,chat-answer-citations" THEME=both`, round v0.11 once tagged, otherwise the working copy on `main`).

## Global Constraints

- Keep the chevron icons: `ChevronLeft` expanded, `ChevronRight` collapsed (the chat panel toggle uses a sidebar icon; they must stay distinct).
- Accessible names stay "Collapse navigation" / "Expand navigation"; `aria-expanded={!collapsed}`; tooltip = label.
- DOM / tab order: brand link, toggle, nav links, user menu.
- The toggle is the same element in both states (not remounted), so focus stays on it after pressing.
- No width transition is added.
- Visual rules from `DESIGN.md`; tokens only (`--sp-*`, `--r-sm`), no raw colors.

## Review Focus

- Keyboard user presses the toggle: focus stays on the toggle in the new state (test: focus remains after toggling through `AppShell`-like wrapper).
- Expanded tooltip "Collapse navigation" must not overflow past the nav's right edge into the clipped area (existing right-aligned rule must still match the button's new place).
- Rail tooltip "Expand navigation" opens to the right like the other rail tooltips.
- Long brand / narrow nav: the brand must shrink (`min-width: 0`) rather than push the button out of the 208px row.
- Dark theme: ghost button and row have no hard-coded colors.

---

### Task 1: Toggle in the top brand row

**Files:**
- Modify: `web/src/components/SideNav/SideNav.tsx`
- Modify: `web/src/components/SideNav/SideNav.module.css`
- Modify: `web/src/components/SideNav/SideNav.test.tsx`
- Modify: `DESIGN.md` (§App shell "Left nav" bullet, §Chat header paragraph)

**Interfaces:**
- Consumes: `SideNav({ collapsed, onToggle, recent })` (unchanged), `IconButton` from `../Button/IconButton`.
- Produces: nothing new for other modules.

- [ ] **Step 1: Write the failing tests** — add to the `describe("SideNav")` block in `SideNav.test.tsx`:

```tsx
  it("puts the collapse toggle at the top, after the brand and before the items", () => {
    renderNav();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const brand = within(nav).getByRole("link", { name: "Smart Tutor, Library" });
    const toggle = within(nav).getByRole("button", { name: "Collapse navigation" });
    const library = within(nav).getByRole("link", { name: "Library" });
    const user = within(nav).getByRole("button", { name: /Ada Lovelace/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(brand.compareDocumentPosition(toggle) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggle.compareDocumentPosition(library) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(library.compareDocumentPosition(user) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("tabs from the brand to the toggle, then to the first item", async () => {
    renderNav();
    await userEvent.tab();
    expect(screen.getByRole("link", { name: "Smart Tutor, Library" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Collapse navigation" })).toHaveFocus();
    await userEvent.tab();
    expect(screen.getByRole("link", { name: "Library" })).toHaveFocus();
  });

  it("keeps focus on the toggle after it changes state", async () => {
    function Harness() {
      const [collapsed, toggle] = useNavCollapsed();
      return <SideNav collapsed={collapsed} onToggle={toggle} />;
    }
    render(
      <SessionContext.Provider value={{ name: "Ada Lovelace", signOut: vi.fn() }}>
        <MemoryRouter initialEntries={["/library"]}>
          <Harness />
        </MemoryRouter>
      </SessionContext.Provider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Collapse navigation" }));
    const expand = screen.getByRole("button", { name: "Expand navigation" });
    expect(expand).toHaveFocus();
    expect(expand).toHaveAttribute("aria-expanded", "false");
  });
```

If the user-menu button's accessible name differs from `/Ada Lovelace/`, read `UserMenu.tsx` and use its actual name.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/components/SideNav`
Expected: "puts the collapse toggle at the top…" and the tab test FAIL (toggle comes after the items today). The focus test may already pass — that is fine; it guards the refactor.

- [ ] **Step 3: Move the toggle in `SideNav.tsx`** — replace the brand link and the foot with:

```tsx
      <div className={styles.head}>
        <Link className={styles.brand} to="/library" aria-label="Smart Tutor, Library">
          <BrandMark size="sm" iconOnly={collapsed} />
        </Link>
        <IconButton
          label={collapsed ? "Expand navigation" : "Collapse navigation"}
          icon={collapsed ? ChevronRight : ChevronLeft}
          aria-expanded={!collapsed}
          onClick={onToggle}
          className={styles.collapse}
        />
      </div>
```

(the groups stay between the head and the foot) and the foot becomes:

```tsx
      <div className={styles.foot}>
        <UserMenu name={name} onSignOut={signOut} compact={collapsed} />
      </div>
```

- [ ] **Step 4: Update `SideNav.module.css`**

- `.sidenav` padding becomes `0 var(--sp-2) var(--sp-2)` (the head row starts at the top edge, like the chat header).
- Replace the `.brand` rule and add `.head`:

```css
/* One 40px row at the top, level with the chat header: the brand on the left, the collapse chevron on the right (brief P8). */
.head { display: flex; align-items: center; gap: var(--sp-1); min-height: 40px; margin-bottom: var(--sp-2); }
.brand { display: block; min-width: 0; padding: 0 var(--sp-2); text-decoration: none; border-radius: var(--r-sm); }
```

- `.collapse { justify-self: end; }` becomes `.collapse { flex: none; margin-left: auto; }`. Keep the expanded tooltip rule below it unchanged.
- In the rail section, replace `.collapsed .brand { … }` and `.collapsed .collapse { … }` with:

```css
/* On the rail the chevron sits under the logo, both centered, above the first item. */
.collapsed .head { flex-direction: column; gap: var(--sp-1); padding-top: var(--sp-2); }
.collapsed .brand { padding: 0; display: grid; justify-items: center; }
.collapsed .collapse { margin-left: 0; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/components/SideNav src/components/AppShell src/app`
Expected: all PASS.

- [ ] **Step 6: Update `DESIGN.md`**

- §App shell "Left nav" bullet: replace "A chevron at the bottom collapses the nav to a 56px icon rail" with "A chevron in the top brand row (a 40px row level with the chat header, right of the logo; below the logo on the rail) collapses the nav to a 56px icon rail".
- §Chat header paragraph: after "…(a sidebar icon; tooltip and accessible name "Hide panel" / "Show panel", `aria-expanded`)", add the sentence: "It shares the top 40px row's alignment with the nav's chevron; the two use different icons so they are not confused."

- [ ] **Step 7: Build and check visually**

Run: `cd web && npm run build`
Expected: success, no type errors.
Then render the mockup states (`make design-shots STATES="shell-nav-collapsed,library-default,chat-answer-citations" THEME=both`) and compare against the running app or a component screenshot if available; at least confirm with `npm run build` and tests.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/SideNav DESIGN.md
git commit -m "Move the nav collapse toggle to the top of the nav (#163)"
```
