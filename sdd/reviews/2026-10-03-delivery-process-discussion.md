# Delivery process discussion: tickets, knowledge base, SDD framework

Date: 2026-10-03. Participants: Product Owner (PO), Project Manager (PM), facilitated by Claude. Status: **decisions 1–4 approved, 5 open** (see [Decisions](#decisions)).

Three questions:

1. How to break `sdd/prd.md` into GitHub issues and label them, using the mattpocock skills (`wayfinder`, `to-tickets`, `triage`, `domain-modeling`, `codebase-design`).
2. How to build and maintain a project knowledge base on top of SDD (OpenWiki, LLM Wiki, or other tools).
3. Which SDD approach fits this greenfield: plain SDD, Spec Kit, OpenSpec, or BMAD.

## Summary of recommendations

| Topic | Recommendation |
|---|---|
| Tickets | Run `/setup-matt-pocock-skills` once. Use GitHub Milestones `M0`–`M4` for Release 1, one parent issue per user story, and vertical-slice sub-issues from `to-tickets`. Use `wayfinder` only for the open decisions. Use the skills' own labels, plus a small `area:*` set. |
| Knowledge base | The authored source of truth stays in `sdd/` (PRD, specs, ADRs, `CONTEXT.md`). Add **OpenWiki code mode** as a generated, agent-facing view, refreshed by a scheduled GitHub Action that opens a PR. Start after M1, when there is real code to describe. |
| SDD framework | Release 1: in-house SDD (the PRD, specs, ADRs and AGENTS.md we already have) driven by the mattpocock skills. Do not adopt Spec Kit or BMAD. Revisit OpenSpec at the M4 retro for change tracking from Release 2 onward. |

PO and PM agree on all three. They differ on one point: the PM wants a dated decision point for OpenSpec or Spec Kit at Release 2, while the PO wants to change only if friction shows up. The proposal below uses decision criteria checked at the M4 retro.

---

## 1. From PRD to GitHub issues

### 1.1 How the skills fit together

The skills are a pipeline. Each one has a single job, and the labels come from the skills themselves.

| Stage | Skill | Input | Output on GitHub | Labels it applies |
|---|---|---|---|---|
| One-time setup | `setup-matt-pocock-skills` | Repo | `docs/agents/` config: tracker = GitHub, triage label mapping, domain doc locations | Creates nothing yet |
| Resolve open decisions | `wayfinder` | A loose goal, e.g. "Release 1 ready to build" | One **map** issue plus child decision tickets, wired with native blocking | `wayfinder:map`; `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, `wayfinder:task` |
| Sharpen language | `grilling` + `domain-modeling` | A decision ticket | Updated `CONTEXT.md` and new ADRs in `sdd/adr/` | None (edits docs) |
| Shape module seams | `codebase-design` | Module or ticket being planned | Deep-module and interface decisions recorded in the ticket or an ADR | None |
| Slice into work | `to-tickets` | PRD section + resolved decisions | Vertical-slice issues with acceptance criteria and native `blocked_by` edges | `ready-for-agent` (default) |
| Intake | `triage` | New bugs and ideas | Agent brief, or triage notes, or close | `bug` / `enhancement` plus one of `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` |
| Build | `implement` / `tdd` | One `ready-for-agent` issue | One PR | — |

Two clarifications for the team:

- `domain-modeling` and `codebase-design` produce **documents**, not labels. They run inside `wayfinder` grilling tickets and during `to-tickets`. Labelling tickets "by skill" means the `wayfinder:*` type labels plus the triage state labels.
- `to-spec` is not needed for Release 1, because the PRD and design spec already are the spec. Use it later for features that start as a conversation.

### 1.2 Hierarchy

```
Milestone  M0 Foundations … M4 Production launch      (PRD §14 exit criteria = milestone description)
 └─ Parent issue  "US-4 Ask a grounded question"      (story text + acceptance criteria, links PRD §8)
     └─ Sub-issue  vertical slice from to-tickets      (≤ one agent session, ~100K tokens)
Wayfinder map  "Release 1: open decisions"             (wayfinder:map; children = decision tickets)
```

- **Milestones** carry the release dimension, so no `r1` to `r5` labels are needed. Later releases get milestones `M5`–`M14` when planning starts.
- **Parent issues** are per user story (US-1 … US-13b). Cross-cutting work that is not a story (M0 infra, CI/CD, the eval harness, isolation suite) gets a parent per PRD section, e.g. "PRD §10 Evaluation harness".
- A slice may touch several stories. Attach it to the story whose acceptance criteria it closes, and mention the others in the body.

### 1.3 Label taxonomy (keep it small)

| Family | Labels | Owner |
|---|---|---|
| Category | `bug`, `enhancement` (already exist) | `triage` |
| State | `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix` | `triage`, `to-tickets` |
| Wayfinder | `wayfinder:map`, `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, `wayfinder:task` | `wayfinder` |
| Area | `area:knowledge`, `area:tutoring`, `area:learning`, `area:accounts`, `area:insights`, `area:web`, `area:infra`, `area:evals` (`area:graph` from Release 2) | Humans and `to-tickets` |
| Risk flag | `isolation` (touches learner data; needs a test in `backend/tests/isolation/`, per AGENTS.md) | Humans |

Priority, size, iteration and status live in **Projects v2 fields**, not labels. The board: fields `Status` (Todo, In progress, In review, Done), `Priority` (P0–P3), `Size` (S/M/L), plus Milestone. Views: *Frontier* (open, unblocked, unassigned, `ready-for-agent`), *By milestone*, *Needs a human* (`ready-for-human`, `needs-info`, open `wayfinder:grilling`).

### 1.4 Definition of Ready (slice)

- Links its PRD section and story ID (e.g. "PRD §8 US-4, §9.3").
- Acceptance criteria are testable and copied or narrowed from the story, not invented.
- Blocking edges are set with native GitHub dependencies.
- It has an area label and, if it touches learner data, the `isolation` label.
- It cuts through every layer it needs (schema → MCP/API → UI → test) and is demoable on its own.
- It uses `CONTEXT.md` terms (subject, content, document, thread, Lesson Note, learning record).

### 1.5 Release 1 order: walking skeleton first

The PO's first draft ordered epics as auth → upload → chat. The PM and facilitator recommend one thin tracer bullet through every component first, then widening it:

1. **M0 remainder as a wayfinder map** ("Release 1 ready to build"). These are real open decisions or tasks, not build slices:
   - `wayfinder:task` Verify Bedrock access: Nova embeddings (sync) and Nova 2 Lite streaming with a tool call.
   - `wayfinder:research` + `wayfinder:task` Docling CPU benchmark and a CPU-only PyTorch worker image.
   - `wayfinder:prototype` Forwarded JWT agent → MCP in Compose.
   - `wayfinder:grilling` Subject-detection confidence rule (PRD §9.2): what counts as a "clear" match?
   - `wayfinder:grilling` Chunking parameters and the relevance gate threshold.
2. **Walking skeleton (one slice per layer path, P0):** sign in → upload one PDF (no dedupe) → Docling → chunk → embed → choose one subject → ask → streamed answer with one citation. Isolation test for the search tool included.
3. **Widen by story**, in roughly this order: US-2/US-11 (states, retry, SHA-256 dedupe) → US-2b/US-10b (suggestions, shared catalog, name check) → US-3/US-3b (detection, growth to 3) → US-5/US-6 (decline log, injection resistance with adversarial PDFs) → US-7/US-8 (notes, learning records, idle sweeper) → US-10/US-13/US-13b (management screens) → US-9 (usage, rate limits) → US-12 hardening → M4 production items.

Example slices that `to-tickets` should produce (draft, for calibration only):

| Parent | Slice | Blocked by |
|---|---|---|
| US-1 | Sign in with Keycloak; empty My library shows "Upload your first document"; unauthenticated API returns 401 | — |
| US-2 | Presigned upload of one PDF → worker runs Docling → document reaches *ready* (one hard-coded subject) | US-1 slice, Docling decision |
| US-4 | Ask in a single-subject thread → MCP search filtered by `can_read` → streamed answer with title+page citation; isolation test with two learners | US-2 slice, JWT decision |
| US-11 | Server SHA-256 insert-or-get links a duplicate to existing content; no re-embedding; reaches *choose subjects* ≤ 10 s | US-2 slice |
| US-2b | Three subject suggestions within 30 s p95; keep 1–3; typed name trimmed, near-duplicate mapped | US-2 slice |
| US-3b | Thread grows to a second subject with notice; refuses a fourth with "New conversation" carrying the question | US-3 slice |

### 1.6 Creating issues safely

`to-tickets` already publishes issues in dependency order and sets native blocking edges. It also asks for approval of the breakdown first, which is the dry run. For bulk creation outside the skill (e.g. the 15 story parents):

- Generate from a reviewed file (`.scratch/r1-parents.md`) and print the planned `gh` commands first.
- Make it idempotent: before creating, search for an exact title (`gh issue list --search "in:title \"US-4 Ask a grounded question\"" --state all`) and skip if found.
- Wire blocking with the REST dependency endpoint, which needs the blocker's **database id**:
  `gh api --method POST repos/konica/agent-tutor/issues/<n>/dependencies/blocked_by -F issue_id=<blocker database id>`.
  (Note: `gh issue edit` has no `--blocking` flag.)
- Link parents with the sub-issues API (`repos/{owner}/{repo}/issues/<parent>/sub_issues`).

### 1.7 Cadence and WIP for agent-driven work

- Daily or per session: an agent takes the top Frontier ticket, assigns it (the claim), and opens one PR.
- WIP: at most one in-progress slice per driving developer and one open PR awaiting review per agent session. Review is the bottleneck, not generation.
- Twice weekly: `/triage` the intake buckets. Weekly: work one `wayfinder:grilling` ticket with the PO.
- Per milestone: re-run `to-tickets` on the next stories, so slices are cut against the code as it actually exists.

---

## 2. Knowledge base

### 2.1 What the team needs from it

| Need | Where it lives |
|---|---|
| What we build and why | `sdd/prd.md` (authored, versioned) |
| How it is structured | `sdd/specs/`, module docstrings and READMEs |
| Why we chose X | ADRs in `sdd/adr/` (written by `domain-modeling` when a decision is hard to reverse, surprising, and a real trade-off) |
| Shared language | `CONTEXT.md` (seeded from PRD §4 glossary, kept current by `domain-modeling`) |
| Traceability: story → ticket → PR → eval | GitHub: parent issue per story, sub-issue slices, PR "Closes #n", eval dataset examples tagged with story ID |
| "How does the code actually work today?" | **Generated** wiki (below) |

### 2.2 Options evaluated

| Option | What it is | Fit |
|---|---|---|
| **OpenWiki (LangChain)** | Open-source CLI built on Deep Agents. Code mode writes a Markdown wiki to `openwiki/` and adds a pointer block to `AGENTS.md`/`CLAUDE.md`. **Grounded Claims** tie facts to versioned line ranges and refresh pages when evidence changes. Scheduled GitHub Action runs `openwiki code --update` and opens a PR. Supports Bedrock as a provider, plus LangSmith tracing. Output is Open Knowledge Format Markdown; `openwiki visualize` serves a local viewer. | **Strong.** Same ecosystem we use (Bedrock, LangSmith, LangGraph); output reviewed like code; agents are the primary audience. |
| **LLM Wiki pattern (Karpathy, Apr 2026)** | A pattern, not a product: `raw/` immutable sources, `wiki/` LLM-maintained pages, a schema in `CLAUDE.md`, with ingest / query / lint operations and `index.md` + `log.md`. | Good for **research knowledge** (papers on RAG, Docling, Bedrock quirks, eval findings). OpenWiki is effectively this pattern packaged for code. |
| DeepWiki / Devin wiki | Hosted, auto-generated repo wiki | Weak: hosted outside our control, private-repo access concerns, not versioned with the code. |
| MkDocs Material / Docusaurus | Human-facing static site | Later, if we need a human docs site; not needed for Release 1. |
| Backstage TechDocs | Developer portal | Overkill for one product and a small team. |
| Log4brains | ADR browser | Nice-to-have; plain Markdown ADRs suffice. |

### 2.3 Recommendation

Use three layers. Only the first is a source of truth.

1. **Authored (source of truth), in `sdd/`:** PRD, specs, ADRs, `CONTEXT.md`. Changed only by PR, per AGENTS.md.
2. **Generated (agent view), in `openwiki/`:** OpenWiki code mode, with `openwiki/INSTRUCTIONS.md` telling it to treat `sdd/` as authoritative, cite PRD sections, and cover modules, ports, data flow, the ingestion pipeline and MCP tools. Weekly scheduled Action plus manual runs at milestone ends; output arrives as a PR and is reviewed like code. Set `OPENWIKI_TELEMETRY_DISABLED=1`; use Bedrock through an OIDC-assumed CI role, not static keys.
3. **Research notes (optional), LLM Wiki pattern:** a small `research/` wiki for external knowledge the team gathers (the mattpocock `research` skill already writes Markdown findings that can feed it).

Timing: the code is still a scaffold, so a generated wiki today would mostly restate the design spec. **Pilot OpenWiki at the end of M1**, compare agent token use and rediscovery on a few tickets, then keep or drop it.

Risks: generated text can be wrong or stale (mitigated by Grounded Claims and PR review, and by never treating it as authoritative); token cost per run (mitigated by no-op updates and weekly cadence); a third place to look (mitigated by the pointer block in `AGENTS.md` that tells agents when to use it).

---

## 3. SDD framework choice

### 3.1 Comparison

| | In-house SDD + mattpocock skills | Spec Kit (GitHub) | OpenSpec (Fission AI) | BMAD Method |
|---|---|---|---|---|
| Core idea | Our PRD, specs, ADRs, AGENTS.md; skills move work through the tracker | Constitution → specify → plan → tasks → implement, per feature | Living specs plus change proposals: `/opsx:propose` → `/opsx:apply` → `/opsx:archive` | Multi-agent personas (product, architect, UX, dev, test) produce PRD, architecture, epics, stories |
| Artifacts | `sdd/prd.md`, `sdd/specs/`, `sdd/adr/`, `CONTEXT.md`, GitHub issues | `.specify/` constitution; `specs/NNN-feature/` spec, plan, tasks | `openspec/specs/` (current truth by capability), `openspec/changes/` (deltas) | PRD, architecture doc, epics and story files |
| Ceremony | Low | Medium–high | Low | High |
| Fit with an existing PRD | Native | Duplicates it: the constitution overlaps AGENTS.md and per-feature specs fork the PRD | Good later: the PRD could be split into capability specs | Duplicates it: regenerates PRD and architecture we already have |
| Change tracking after launch | ADRs plus PRD version bumps (gets heavy as the PRD grows) | Per-feature folders | **Strongest:** built for brownfield deltas | Story files |
| Tracker integration | Native GitHub issues, blocking, triage | Tasks live in Markdown | Tasks live in Markdown | Stories live in Markdown |
| Claude Code support | Installed | Yes (30+ agents) | Yes (30+ agents) | Yes (plugin marketplace) |
| Adoption (stars, Oct 2026) | n/a | ~140k | ~71k | ~54k |

### 3.2 Recommendation

**Release 1: in-house SDD with the mattpocock skills.** We already have what these frameworks would generate: a reviewed PRD v2.1 with stable story IDs, an approved structure spec, ADR folder, AGENTS.md conventions, and an issue-tracker workflow. Adding Spec Kit or BMAD now would create a second spec that drifts from the PRD, and a second workflow that competes with `to-tickets`/`triage` for the same stage. Pick one workflow per stage.

**Do not adopt BMAD.** Its value is generating the PRD and architecture through role personas; we have both, and the persona ceremony costs a small team more than it returns.

**Do not adopt Spec Kit for Release 1.** Its per-feature folders would duplicate PRD §8–§9, and its tasks live in Markdown rather than in GitHub issues with native blocking.

**Revisit OpenSpec at the M4 retro.** After launch, most work becomes changes to an existing system, which is what OpenSpec is built for. Its `specs/` (current truth by capability) and `changes/` (proposed deltas, archived on merge) could replace the growing single PRD. Adopt it for Release 2 if at least two of these are true at M4:
- `sdd/prd.md` has grown too large to load as context (PRD changes regularly conflict, or agents read only parts of it).
- More than a few PRs per milestone needed PRD edits to stay consistent.
- Reviewers can't tell from a PR which requirement it changes.

If adopted, OpenSpec would own the spec (proposal and capability specs), and the mattpocock skills would keep owning the tracker (slicing, triage, decisions).

---

## Corrections to the first drafts

Recorded so the team does not reuse them:

- Slices are sized to one agent session (~100K tokens), not to hours of work.
- `gh issue edit` has no `--blocking` flag; blocking uses the REST dependencies endpoint.
- Release scope belongs in Milestones (`M0`–`M14`, PRD §14) rather than `r1`–`r5` labels, to avoid two sources for the same fact.
- OpenSpec is a delta-spec workflow and BMAD is a multi-persona planning method; neither is about flow diagrams or state machines.

## Decisions

Recorded 2026-10-03 by the product owner.

1. **Approved:** label taxonomy (§1.3) and the Milestone → story parent → slice hierarchy (§1.2). Added `area:subjects` for the module introduced in PRD v2.2. Applied: labels, milestones M0–M4, story parents US-1 … US-13b.
2. **Approved:** `/setup-matt-pocock-skills` with GitHub tracker and default triage labels. `CONTEXT.md` lives at the **repo root** (the skills' default, found by agents without extra config); ADRs stay in `sdd/adr/`. Config in `docs/agents/`.
3. **Approved:** the "Wayfinder: Release 1 ready to build" map with decision tickets from the M0 exit criteria.
4. **Approved, changed:** run OpenWiki **now** instead of piloting at the end of M1 (§2.3). Weekly workflow `.github/workflows/openwiki-update.yml` on Bedrock; it skips until the repo variable `OPENWIKI_AWS_ROLE_ARN` points at an OIDC role.
5. **Open:** in-house SDD for Release 1 with OpenSpec criteria at M4 (§3.2).
6. **Approved:** skill split. mattpocock skills decide what to build and run the tracker; superpowers skills (`brainstorming`, `writing-plans`, `subagent-driven-development`, `test-driven-development`, review, finishing) build one ticket, saving specs and plans under `sdd/`. Recorded in `AGENTS.md` → "Workflow: which skill does what".

## Sources

- mattpocock skills v1.2.3 (installed): `wayfinder`, `to-tickets`, `triage`, `setup-matt-pocock-skills` (`triage-labels.md`, `issue-tracker-github.md`) — https://github.com/mattpocock/skills
- OpenWiki docs: https://docs.langchain.com/oss/openwiki/overview, `/oss/openwiki/code-mode`, `/oss/openwiki/automate-updates`
- Spec Kit: https://github.com/github/spec-kit
- OpenSpec: https://github.com/Fission-AI/OpenSpec
- BMAD Method: https://github.com/bmad-code-org/BMAD-METHOD
- LLM Wiki pattern overview: https://blog.starmorph.com/blog/karpathy-llm-wiki-knowledge-base-guide
- Framework landscape: https://www.softwareseni.com/the-30-plus-framework-landscape-navigating-spec-driven-development-options-in-2026
