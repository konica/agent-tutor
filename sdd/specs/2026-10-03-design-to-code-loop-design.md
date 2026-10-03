# Design-to-code loop: PRD, brief, Open Design mockups, tickets

| | |
|---|---|
| **Status** | Draft, for PO review |
| **Date** | 2026-10-03 |
| **Owner** | Thao Dinh (PO) |
| **Applies to** | `sdd/prd.md`, `sdd/design/`, GitHub issues, `web/` |

## 1. Problem

The product moves through five artifacts: idea → PRD → design brief → Open Design mockups → tickets → code. Today they drift apart:

- Tickets are cut from the PRD without the mockups, so agents build screens nobody designed, or miss states the mockups show.
- Mockups live only in Open Design on one laptop (`%APPDATA%\Open Design\…`). A new agent session, a cloud agent, or CI cannot see them, and nothing records which PRD version a mockup answers.
- When a mockup reveals a business problem, the PRD changes, but nothing tells us which mockups and tickets are now stale.
- PRD, brief and process documents sit on separate unmerged branches, so there is no single current version.

## 2. Goal and success criteria

One loop, with the repo as the hub. A fresh coding-agent session that is given only a ticket number can find the PRD sections, the exact mockup states, and the design system it must use, and build a screen that matches the accepted mockup.

Success means:

1. Every UI ticket names the accepted design round and the state ids it implements.
2. Every accepted round is in git, with the brief and PRD versions it answers.
3. A PRD or brief change lists the affected state ids and open tickets in one command.
4. No feature slice touches `web/` before the web foundation ticket is done.

Out of scope: Claude Design, Figma, automated pixel diffing in CI, and design work for Release 2+ beyond the wireframes the brief already asks for.

## 3. Principles

- **The repo is the source of truth; Open Design is where design is edited.** Agents never depend on Open Design running.
- **State ids are the shared key.** `<screen>-<state>@v<brief>` (brief §11) names a state in the brief, the prototype, tickets, and tests.
- **Only accepted rounds count.** Tickets point at accepted rounds, never at a draft in Open Design.
- **Order of authority:** PRD → brief → accepted round → ticket → code. A lower artifact never changes a higher one silently; it raises feedback (§8).

## 4. Repository layout

```
sdd/
  prd.md
  design/
    brief.md                 # design brief, versioned v0.x (brief §13)
    design.config.json       # Open Design project id and data dir (no secrets)
    rounds/
      v0.3/                  # one folder per accepted round, named after the brief version
        ROUND.md             # provenance and acceptance (§4.1)
        states.json          # state index (§4.2), generated
        prototype/           # verbatim copy of the Open Design project files
web/
  scripts/design/            # pull, shots, diff (§5)
.design-shots/               # rendered screenshots, git-ignored
```

- Old rounds stay in git so rounds can be compared and old tickets still resolve.
- Screenshots are not committed. The prototype is committed, so any state can be rendered on demand.
- Expected size: about 300 KB of HTML, CSS and JS per round.

### 4.1 `ROUND.md`

```markdown
# Design round v0.3
- Brief: v0.3 (sdd/design/brief.md @ <commit>)
- PRD: v2.1
- Open Design project: 5632ee5d-5009-4b7b-86a1-827855c84d52
- Pulled: 2026-10-03, accepted by: Thao Dinh (PO) on 2026-10-xx
- States: <count from states.json>
- Open feedback: Q7, D1–D12 (see brief Feedback log)
```

### 4.2 `states.json`

Generated from the prototype; never edited by hand.

```json
[
  { "id": "chat-fourth-subject-refused", "group": "Chat", "ref": "§6.6 · US-3–10",
    "desc": "…", "stories": ["US-3b"] }
]
```

`stories` is parsed from `ref`. A range such as `US-3–10` expands to every story id in it; a state may therefore list several stories.

## 5. Tooling

Node scripts in `web/scripts/design/`, run through `npm run` in `web/` and wrapped by `Makefile` targets. Playwright is a dev dependency of `web/`.

| Command | What it does |
|---|---|
| `make design-pull ROUND=v0.3` | Copies the Open Design project into `sdd/design/rounds/v0.3/prototype/`, skipping `.file-versions/`, `.od-*` and nested old rounds. Opens the prototype in headless Chromium, reads `window.ST.STATES`, writes `states.json`, and writes `ROUND.md` with "accepted by" left blank. Refuses to overwrite an existing round unless `FORCE=1`. |
| `make design-shots ROUND=v0.3 STATES="chat-*" THEME=light` | Renders each matching state at 1440×900 to `.design-shots/v0.3/<id>.<theme>.png`. Agents run this to see the target before and after building. |
| `make design-diff FROM=v0.2 TO=v0.3` | Prints state ids added, removed and changed (by `desc` or `ref`), then lists open GitHub issues that mention a removed or changed id (`gh issue list --search`). |

Design notes:

- `design-pull` reads the project folder directly from `OD_DATA_DIR/projects/<id>/`. It does not use the Open Design daemon or MCP server, because those only run on the PO's machine and their port and paths change between app versions.
- `design.config.json` holds the project id and a default data dir. Override with `OD_DATA_DIR`.
- The scripts fail loudly when `window.ST.STATES` is missing, empty, or has duplicate ids.
- `states.json` stores bare ids (`chat-new`); the round folder carries the version. Tickets, PRs and tests write the full form (`chat-new@v0.3`).

### 5.1 Contract for the designer (added to brief §11)

The prototype must:

1. Expose `window.ST.STATES` as an array of `{ id, group, ref, desc }`.
2. Open any state directly at `index.html#/<state-id>`.
3. Keep design-review chrome (the review bar) out of the app shell, and hide it when the URL has `?shot=1`.

Round v0.3 already meets 1 and 2. Point 3 is new and goes into Appendix A of the brief.

## 6. Tickets

### 6.1 Web foundation ticket (PO rule)

Before any feature slice that touches `web/`, one ticket sets up the site. Every slice with `area:web` is blocked by it, through native GitHub blocking.

- **Parent:** "Web foundation: shell, design system, layout" (cross-cutting parent, like "PRD §10 Evaluation harness").
- **Slice "Web foundation"** delivers:
  - `web/src/design/tokens.css`: all tokens from the accepted round's CSS, light and dark, with the theme switch.
  - `web/src/components/`: the brief §10 components page — Button, SubjectChip, StateBadge, Banner, Notice, Excerpt, Citation, EmptyState, Dialog, SidePanel, Toast, Tabs, FilterBar, TableRow, DropZone, UploadTrayItem, StatusLine. Picker and Tray as shells without data.
  - App shell (brief §6.1): left navigation in the brief's order, slots reserved for R2/R3 items, Library badge slot, user menu, global upload tray container, skip link, live region.
  - Routing for every Release 1 screen, each rendering an empty page with its title.
  - Auth guard wired to Keycloak, enough to show the user menu and sign out.
  - `/dev/components` page that mirrors the prototype's components page.
- **Done when:** `npm run build` passes; `/dev/components` and the empty shell match `design-shots` for `components@v0.3` and the shell around `library-empty@v0.3` in light and dark; keyboard navigation and visible focus work in the shell (brief §10).
- If the foundation needs more than one agent session, `to-tickets` splits it (for example tokens + components, then shell + routing). All parts must be done before feature slices start.

### 6.2 Story parents

Each story parent (US-1 … US-13b) gets a `## Design` section, generated from `states.json`:

```markdown
## Design
Round: v0.3 (`sdd/design/rounds/v0.3/`, PRD v2.1)
States: `chat-subject-added@v0.3`, `chat-maximum-reached@v0.3`, `chat-fourth-subject-refused@v0.3`, `chat-new-from-refused@v0.3`
```

A one-off script backfills the existing parents #8–#24. It edits only the `## Design` section and prints the planned edits before applying them.

### 6.3 Definition of Ready (adds to the delivery-process §1.4)

A slice that touches `web/`:

- names the accepted round and the exact state ids it implements, a subset of its parent's `## Design` list;
- is blocked by the Web foundation slice;
- has no state id from a round older than the parent's current round.

### 6.4 Definition of Done for UI slices

- Every listed state is reachable in the running app with the brief's sample data or a fixture.
- The agent has rendered `design-shots` for those states and a Playwright screenshot of the app for the same states, and fixed differences in layout, wording, and states. Colours and spacing come only from tokens.
- New components or tokens are added to `web/src/components/` and `/dev/components`, not inlined in a feature.
- The PR description lists the state ids and attaches the side-by-side screenshots.

## 7. Agent instructions (`AGENTS.md`)

Add a "Design inputs" section:

1. Read the ticket's `## Design` section, then `sdd/design/rounds/<round>/ROUND.md`.
2. Run `make design-shots` for the ticket's states and look at them before writing code.
3. Treat the prototype as a spec, not code to copy: rebuild with `web/src/components/` and tokens. Never paste prototype HTML or CSS into a feature.
4. If the mockup and the PRD disagree, follow the PRD, and add the conflict to the PR description and the brief's Feedback log.
5. Do not read Open Design directly; only accepted rounds in the repo count.

## 8. Change loop: when a mockup reveals a business problem

Each step is one PR (or one PR for steps 1–2 together):

1. **Record.** Add designer questions and the PO's own findings to the brief's Feedback log, each marked *→ PRD change*, *→ brief change*, or *rejected*.
2. **Change the PRD**, bumping its version, then the brief: new version, §0 "What changed" with the state ids to redo, changelog row (brief §13).
3. **Design.** Paste brief Appendix A into Open Design and produce the round.
4. **Accept.** The PO reviews the round, then runs `make design-pull ROUND=v0.x`, fills "accepted by" in `ROUND.md`, and opens a PR.
5. **Re-point tickets.** `make design-diff FROM=<old> TO=<new>` lists affected issues. Update their `## Design` sections and re-run `to-tickets` for stories whose states changed. Closed tickets are not reopened; changed behavior becomes a new slice.

Rules:

- Mockups never get ahead of the brief, and tickets never point at an unaccepted round.
- A round that only polishes visuals (same state ids) still gets a new brief minor version, so `ROUND.md` stays honest.

## 9. Prerequisite: one `main`

Before this loop starts, merge the open branches so `main` holds the current PRD, brief and process documents:

1. `docs/delivery-process-discussion` (delivery process, `CONTEXT.md`)
2. `prd/v2.3-pdf-text-loader` (PRD v2.3, ADR 0005)
3. `docs/design-brief-prd-v2` (brief v0.3, moved to `sdd/design/brief.md`)

Then the first implementation PR adds the tooling and round v0.3. Brief v0.3 answers PRD v2.1, so before round v0.3 is accepted, the PO checks whether PRD v2.2 and v2.3 change any user-facing behavior. If they do, the brief moves to v0.4 first.

## 10. Rollout

1. Merge the branches in §9.
2. PR 1: `sdd/design/` layout, scripts, Makefile targets, `AGENTS.md` "Design inputs", brief §11 contract and Appendix A update.
3. PR 2: pull and accept round v0.3 (or v0.4).
4. Backfill `## Design` on story parents #8–#24.
5. Create the Web foundation parent and slice; block every `area:web` slice on it.
6. Process the open feedback Q7 and D1–D12 through §8.

## 11. Risks

| Risk | Mitigation |
|---|---|
| The prototype format changes in a later Open Design version. | `design-pull` depends only on files and `window.ST.STATES`, which the brief requires (§5.1). |
| Repo growth from committed prototypes. | About 300 KB per round; screenshots stay out of git. |
| Agents copy prototype HTML instead of using components. | `AGENTS.md` rule, Definition of Done, and review of the PR's component use. |
| States without a story id (overview, wireframes). | `stories` is empty; they are not assigned to tickets. R2/R3 wireframe states are ignored until those releases. |
