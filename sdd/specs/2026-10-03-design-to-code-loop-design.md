# Design-to-code loop: PRD, brief, Open Design mockups, tickets

| | |
|---|---|
| **Status** | Approved by the PO, 2026-10-03 |
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

- **The repo is the only home of the design.** The prototype lives in `sdd/design/prototype/`, and Open Design opens that folder as an imported-folder project and edits it in place. Agents never depend on Open Design running.
- **State ids are the shared key.** `<screen>-<state>@v<brief>` (brief §11) names a state in the brief, the prototype, tickets, and tests.
- **Only accepted rounds count.** An accepted round is a git tag (`design-v0.3`). Tickets point at tags, never at the working copy, which may hold a round in progress.
- **Order of authority:** PRD → brief → accepted round → ticket → code. A lower artifact never changes a higher one silently; it raises feedback (§8).

## 4. Repository layout

```
sdd/
  prd.md
  design/
    README.md                # how to open the prototype in Open Design, and the rules below
    brief.md                 # design brief, versioned v0.x (brief §13)
    rounds.md                # log of accepted rounds (§4.1)
    states.json              # state index of the working copy (§4.2), generated
    prototype/               # the whole Open Design project, edited in place by Open Design
      history/               # exported Open Design conversations (designer questions, owner answers)
web/
  scripts/design/            # states, shots, diff (§5)
.design-shots/               # rendered screenshots, git-ignored
```

- One folder, edited in place; git history and tags replace copied round folders. Any accepted round can be read with `git show design-v0.3:sdd/design/prototype/…` or rendered with `make design-shots ROUND=v0.3`.
- Screenshots are not committed. The prototype is committed, so any state can be rendered on demand.
- Open Design's own files (`.file-versions/`, `.od-frames/`, `.od-skills/`) are committed with the prototype, so the folder is the complete project. Git tags, not `.file-versions/`, mark accepted rounds.
- The designer may keep an older round inside the prototype for comparison (round v0.3 keeps `prototype/v0.2/`). That is the designer's choice; tickets still use tags.

### 4.1 `rounds.md`

One row per accepted round, newest first:

```markdown
| Round | Tag | Brief | PRD | States | Accepted | Open feedback |
|---|---|---|---|---|---|---|
| v0.3 | `design-v0.3` | v0.3 | v2.1 | <n> | 2026-10-xx, Thao Dinh (PO) | Q7, D1–D12 |
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
| `make design-states` | Opens `sdd/design/prototype/index.html` in headless Chromium, reads `window.ST.STATES`, and writes `sdd/design/states.json`. Run before committing prototype changes; CI checks it is current. |
| `make design-accept ROUND=v0.3` | Runs `design-states`, adds the row to `rounds.md` (PRD and brief versions read from their headers), and prints the `git tag design-v0.3` command to run after the PR merges. |
| `make design-shots ROUND=v0.3 STATES="chat-*" THEME=light` | Exports the tag's prototype to a temp folder (`git archive`) and renders each matching state at 1440×900 to `.design-shots/v0.3/<id>.<theme>.png`. Without `ROUND`, renders the working copy. Agents run this to see the target before and after building. |
| `make design-diff FROM=v0.2 TO=v0.3` | Compares `states.json` at the two tags: state ids added, removed and changed (by `desc` or `ref`), then lists open GitHub issues that mention a removed or changed id (`gh issue list --search`). |

Design notes:

- No script talks to the Open Design app, daemon, or MCP server. They only run on the PO's machine, and their ports and paths change between app versions.
- The scripts fail loudly when `window.ST.STATES` is missing, empty, or has duplicate ids.
- `states.json` stores bare ids (`chat-new`); the git tag carries the version. Tickets, PRs and tests write the full form (`chat-new@v0.3`).

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
Round: v0.3 (tag `design-v0.3`, `sdd/design/prototype/`, PRD v2.1)
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

1. Read the ticket's `## Design` section, then its row in `sdd/design/rounds.md`.
2. Run `make design-shots` for the ticket's states and look at them before writing code.
3. Treat the prototype as a spec, not code to copy: rebuild with `web/src/components/` and tokens. Never paste prototype HTML or CSS into a feature.
4. If the mockup and the PRD disagree, follow the PRD, and add the conflict to the PR description and the brief's Feedback log.
5. Do not read Open Design or its data folder. Read the prototype at the ticket's tag, not the working copy, which may hold a round in progress.

## 8. Change loop: when a mockup reveals a business problem

Each step is one PR (or one PR for steps 1–2 together):

1. **Record.** Add designer questions and the PO's own findings to the brief's Feedback log, each marked *→ PRD change*, *→ brief change*, or *rejected*.
2. **Change the PRD**, bumping its version, then the brief: new version, §0 "What changed" with the state ids to redo, changelog row (brief §13).
3. **Design.** Paste brief Appendix A into Open Design and produce the round.
4. **Accept.** The PO reviews the round, then runs `make design-accept ROUND=v0.x`, opens a PR with the prototype, `states.json` and `rounds.md` changes, and tags `design-v0.x` after it merges.
5. **Re-point tickets.** `make design-diff FROM=<old> TO=<new>` lists affected issues. Update their `## Design` sections and re-run `to-tickets` for stories whose states changed. Closed tickets are not reopened; changed behavior becomes a new slice.

Rules:

- Mockups never get ahead of the brief, and tickets never point at an unaccepted round.
- A round that only polishes visuals (same state ids) still gets a new brief minor version, so `rounds.md` stays honest.

## 9. Prerequisite: one `main`

Before this loop starts, merge the open branches so `main` holds the current PRD, brief and process documents:

1. `docs/delivery-process-discussion` (delivery process, `CONTEXT.md`)
2. `prd/v2.3-pdf-text-loader` (PRD v2.3, ADR 0005)
3. `docs/design-brief-prd-v2` (brief v0.3). Its `sdd/design/brief.md` is identical to the copy on this spec's branch, so it merges cleanly.

The prototype moved into the repo on this spec's branch (§12). The first implementation PR adds the tooling. Brief v0.3 answers PRD v2.1, so before round v0.3 is accepted, the PO checks whether PRD v2.2 and v2.3 change any user-facing behavior. If they do, the brief moves to v0.4 first.

## 10. Rollout

1. Merge the branches in §9.
2. PR 1: `sdd/design/` layout, scripts, Makefile targets, `AGENTS.md` "Design inputs", brief §11 contract and Appendix A update.
3. PR 2: run `make design-accept ROUND=v0.3` (or v0.4) and tag it.
4. Backfill `## Design` on story parents #8–#24.
5. Create the Web foundation parent and slice; block every `area:web` slice on it.
6. Process the open feedback Q7 and D1–D12 through §8.

## 11. Risks

| Risk | Mitigation |
|---|---|
| The prototype format changes in a later Open Design version. | The scripts depend only on files and `window.ST.STATES`, which the brief requires (§5.1). |
| Repo growth from committed prototypes. | One folder edited in place (about 520 KB with the kept v0.2 round); git stores only changes. Screenshots stay out of git. |
| Agents copy prototype HTML instead of using components. | `AGENTS.md` rule, Definition of Done, and review of the PR's component use. |
| States without a story id (overview, wireframes). | `stories` is empty; they are not assigned to tickets. R2/R3 wireframe states are ignored until those releases. |
| A round in progress in Open Design shows as uncommitted changes in the PO's checkout. | Expected: commit drafts on a `design/v0.x` branch. Tickets use tags, so drafts never reach agents. |
| Open Design is opened on a worktree that is later deleted. | Open Design must import the PO's main checkout (`C:\Data\Projects\agent-tutor\sdd\design\prototype`), never a `.claude/worktrees/` path. |

## 12. Moving the Open Design project into the repo (done 2026-10-03)

Project `5632ee5d-5009-4b7b-86a1-827855c84d52` ("Smart Tutor Design Round 1") moved from Open Design's data folder into the repo:

| From (`%APPDATA%\Open Design\…\projects\5632ee5d…\`) | To |
|---|---|
| `index.html`, `styles.css`, `v03.css`, `js/`, `v0.2/`, `*.artifact.json` | `sdd/design/prototype/`, byte for byte |
| Design conversation (8 messages, in Open Design's `app.sqlite`) | `sdd/design/prototype/history/2026-10-03-open-design-rounds-1-2.md` (pasted briefs replaced by a pointer) |
| `.file-versions/`, `.od-frames/`, `.od-skills/` | `sdd/design/prototype/` (Open Design's version snapshots, device frames, and its empty skills folder, kept with a `.gitkeep`) |

Brief v0.3 came along from `docs/design-brief-prd-v2` to `sdd/design/brief.md`.

To finish the move, the PO, after this branch merges:

1. In Open Design, imports the folder `C:\Data\Projects\agent-tutor\sdd\design\prototype` as a new project (entry file `index.html`).
2. Continues design work in that project only, and attaches the history file to the first message of the next round so the designer keeps context.
3. Deletes the old project `5632ee5d` in Open Design once the imported one renders correctly.
