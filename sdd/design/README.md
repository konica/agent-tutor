# Design

The design for Smart Tutor lives here and nowhere else. Process and rules: `sdd/specs/2026-10-03-design-to-code-loop-design.md`.

| Path | What |
|---|---|
| `brief.md` | Design brief, the designer's source of truth. Versioned v0.x (brief §13). |
| `prototype/` | The whole Open Design project (pages, styles, scripts, its version snapshots and frames). Open Design edits this folder in place. Open `prototype/index.html` in a browser to review it; `#/<state-id>` opens one state. |
| `prototype/history/` | Exported Open Design conversations: the designer's questions and the owner's answers. |
| `rounds.md` | Accepted rounds, each a git tag `design-v0.x`. Added with the tooling. |
| `states.json` | Index of every state id in the prototype, generated. Added with the tooling. |

## Working in Open Design

1. In Open Design, import the folder `C:\Data\Projects\agent-tutor\sdd\design\prototype` (the main checkout, never a `.claude/worktrees/` path).
2. Start a round by pasting brief Appendix A with `brief.md` attached.
3. Commit work in progress on a `design/v0.x` branch. A round counts only after it is accepted and tagged.

## For coding agents

- Build from the prototype at the ticket's tag (`design-v0.x`), not the working copy.
- The prototype is a spec, not code to copy. Rebuild it with `web/src/components/` and the design tokens.
- Do not read Open Design or its data folder.
