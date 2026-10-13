# Architecture diagrams

Diagrams for the documents in `docs/architecture/`, drawn with the **diagram-design** agent skill (`cathrynlavery/diagram-design`, checked in at `.claude/skills/diagram-design/` and `.agents/skills/diagram-design/`, pinned in `skills-lock.json`) in the **Smart Tutor skin**: the web app's own colours, light and dark, with system fonts so a diagram renders offline and inside Markdown.

## Files

| File | What |
|---|---|
| `<name>.html`, `<name>-dark.html` | The diagram, light and dark. The source of truth: edit these. |
| `<name>.svg`, `<name>-dark.svg` | Exported from the HTML, for GitHub to show inline. Never edit by hand. |
| `smart-tutor-profile.md` | The skin as a diagram-design profile (slug `smart-tutor`) |
| `check_skin_contrast.py` | Checks that every text colour in the profile clears 4.5:1, light and dark |
| `../../../.diagram-design` | The project marker, `profile: smart-tutor`: the skill reads that profile for this repository |

## The skin

Every colour is a token from `web/src/styles/tokens.css` (see `DESIGN.md` → Tokens), so diagrams look like the app.

| Diagram role | Used for | Web token | Light | Dark |
|---|---|---|---|---|
| `paper` | Page background | `--bg` | `#f6f7f9` | `#0e1418` |
| `paper-2` | Secondary fill | `--surface-2` | `#eef1f4` | `#1c262e` |
| `ink` | Main text and lines | `--text` | `#14202b` | `#e8eef2` |
| `ink-strong` | Text on an accent fill | `--on-accent` | `#ffffff` | `#06221f` |
| `muted` | Secondary text, default arrows | `--text-2` | `#4a5866` | `#b3bfc9` |
| `soft` | Small labels, zone labels | `--text-3` | `#5b6875` | `#a0adb8` |
| `rule` | Hairlines | `--text` at 12% | `rgba(20,32,43,0.12)` | `rgba(232,238,242,0.12)` |
| `rule-solid` | Stronger borders | `--border-strong` | `#a9b4be` | `#4a5a66` |
| `accent` | The 1–2 focal elements | `--accent` | `#0b6b66` | `#4cc2b8` |
| `accent-tint` | Fill of a focal box | `--accent` at 8% / 10% | `rgba(11,107,102,0.08)` | `rgba(76,194,184,0.10)` |
| `link` | API and HTTP calls | `--info` | `#1d5fa8` | `#8bbdf3` |
| Node fill | Plain boxes | `--surface` | `#ffffff` | `#151d23` |

| Text role | Font stack (no web fonts) |
|---|---|
| Title, callouts | `--font-display`: Charter, "Bitstream Charter", "Iowan Old Style", "Palatino Linotype", Cambria, Georgia, serif |
| Box names | `--font-body`: system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif |
| Technical labels (ports, names, arrow labels) | `--font-mono`: ui-monospace, "Cascadia Mono", "SF Mono", Menlo, Consolas, monospace |

Choices that are not a one-to-one copy:

- **`link` is `--info`, not the app's link colour `--accent-text`.** That is the accent's teal, and a diagram needs API arrows to read apart from the focal accent.
- **`ink-strong` is `--on-accent`.** It labels an accent fill, so it is white on the light teal and dark teal on the dark one.
- **`rule` and `accent-tint` are translucent**, as the skill expects, so a line or tint never hides what is under it.
- **Paper is the app's cool grey**, not the skill's default warm cream: matching the app wins.

The skill's series palette (radar charts) and terminal skin are left at the skill's values.

## Set up the skin on a new machine

The skill is in the repository, but it reads profiles from your home folder; the `.diagram-design` marker at the repository root points it at `smart-tutor`. Copy the profile there once:

```bash
mkdir -p ~/.diagram-design/profiles
cp docs/architecture/diagrams/smart-tutor-profile.md ~/.diagram-design/profiles/smart-tutor.md
```

After changing a token in `web/src/styles/tokens.css`, update the tables above and `smart-tutor-profile.md` (the `### Semantic roles` table, its `updated:` date), copy it again, and run the contrast check.

## Make a diagram

1. Ask the agent to draw it with the diagram-design skill. With the marker in place it uses the Smart Tutor skin; it renders a light and a dark HTML file here. In the skin, the HTML has no font `<link>`.
2. Run the checks from the repository root:

   ```bash
   python docs/architecture/diagrams/check_skin_contrast.py
   python .claude/skills/diagram-design/scripts/self_check.py --offline docs/architecture/diagrams/<name>.html docs/architecture/diagrams/<name>-dark.html
   ```

   The connector rules are checked by `scripts/verify-geometry.py` in the skill's source repository (`cathrynlavery/diagram-design`), which is not part of the checked-in skill; it takes the same file arguments.
3. Export both to SVG with system fonts:

   ```bash
   python .claude/skills/diagram-design/scripts/export_svg.py docs/architecture/diagrams/<name>.html --system-fonts
   python .claude/skills/diagram-design/scripts/export_svg.py docs/architecture/diagrams/<name>-dark.html --system-fonts
   ```

## Show a diagram in Markdown

GitHub shows an SVG inline but not an HTML file, and it picks the SVG that matches the reader's theme from a `<picture>` element. Link the light HTML under it for the full-size, scrollable version:

```html
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="diagrams/<name>-dark.svg">
  <img alt="<one sentence: what the diagram shows>" src="diagrams/<name>.svg">
</picture>
```

```markdown
[Open the diagram](diagrams/<name>.html) ([dark](diagrams/<name>-dark.html))
```

Leave a blank line before and after the `<picture>` block, so the Markdown around it still renders. The `alt` text matches the SVG's `<desc>`. GitHub shows a linked HTML file as source code; open it from a checkout (or download it) to see the page.
