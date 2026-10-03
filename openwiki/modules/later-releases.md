---
type: module-reference
title: Later-Release Module Placeholders
description: Reference guide for the five scaffold modules reserved for R2 and R3 — graph, catalog, quizzes, recommendations, and reports. Describes what each module will own, its planned key classes, its permitted dependencies, and its position in the module dependency order. All five are currently empty stubs with no domain classes, services, or adapters implemented; build them only when the corresponding release is started.
tags: [modules, research-map, catalog, quizzes, recommendations, reports, graph, r2, r3, r5, stub, roadmap]
verified:
  - by: openwiki/0.7.0
    at: 2026-10-03T03:19:50.688Z
sources:
  - id: openwiki-source-410ab36600fefdde765cb24e
    resource: repo://backend/AGENTS.md
  - id: openwiki-source-070c6307b3860e1806baf566
    resource: repo://backend/pyproject.toml
  - id: openwiki-source-1ba73eecf562b6639eb6c5cf
    resource: repo://backend/src/smart_tutor/catalog/__init__.py
  - id: openwiki-source-f181875ad96ded7adca99f08
    resource: repo://backend/src/smart_tutor/catalog/README.md
  - id: openwiki-source-1023906370c14e884e38d4b7
    resource: repo://backend/src/smart_tutor/graph/__init__.py
  - id: openwiki-source-ace6c0f6fbf505181c7b94e9
    resource: repo://backend/src/smart_tutor/graph/README.md
  - id: openwiki-source-cc4a4d61e730a5b988fde1b5
    resource: repo://backend/src/smart_tutor/quizzes/__init__.py
  - id: openwiki-source-4b252d4f2175ed4df2875012
    resource: repo://backend/src/smart_tutor/quizzes/README.md
  - id: openwiki-source-ee42c71ed8af4c4032cd3595
    resource: repo://backend/src/smart_tutor/recommendations/__init__.py
  - id: openwiki-source-54cb086a305d7df20dce408a
    resource: repo://backend/src/smart_tutor/recommendations/README.md
  - id: openwiki-source-3dd3efff2149a972e2fadbf7
    resource: repo://backend/src/smart_tutor/reports/__init__.py
  - id: openwiki-source-6c08b77fbb9736cfebfb478a
    resource: repo://backend/src/smart_tutor/reports/README.md
  - id: openwiki-source-473ea646d59721d67fc55bbb
    resource: repo://sdd/prd.md
generated: { by: "openwiki/0.7.0", at: "2026-10-03T03:19:50.688Z" }
---

# Later-Release Module Placeholders

Five modules in `backend/src/smart_tutor/` are empty scaffold stubs reserved for Release 2, Release 3, and Release 5. Each has the standard four-layer directory structure (`domain/`, `application/`, `ports/`, `adapters/`) and a `README.md`, but every sub-package contains only a docstring `__init__.py` with no implemented classes. As [AGENTS.md](../../backend/AGENTS.md) states for these modules, **build them only when asked** — do not edit them until the corresponding release is started.

---

## Module dependency order

The full acyclic dependency order enforced by `import-linter` ([Module Structure and Import Rules](../architecture/module-layer-rules.md)) is, from top to bottom:

```
reports
  ↓
recommendations
  ↓
quizzes  |  catalog        (siblings — independent of each other)
  ↓
learning
  ↓
tutoring
  ↓
graph
  ↓
knowledge
  ↓
subjects
  ↓
accounts  |  insights
```

The five later-release modules occupy the top five positions. Each module may only import the `application` layer of modules **below** it in this order. Lower modules never import higher ones. Because `import-linter` already encodes all five modules in this contract, the contracts pass today on the empty scaffolds and will continue to pass as each module is built out.

---

## Module profiles

### `graph` — Release 2 (extended in Release 5)

| Field | Value |
|---|---|
| **Path** | `backend/src/smart_tutor/graph/` |
| **Release** | R2 core; R5 deep-graph extension |
| **Dependency order position** | 6th from top — below `learning`, `tutoring`; above `knowledge` |

**Owns (PRD §9.7, §9.16):** The research map — works (contents grouped by `work_key`), citation links from saved Docling references, a per-subject timeline, reading order (foundational/cited works first, then by year), and reading-path answers. Release 5 adds model-labeled relationships with evidence (`builds_on`, `addresses_limitation_of`, `compares_with`), concept history, and figures/tables via multimodal embeddings.

**Key classes planned:** `Work`, `WorkLink`, `ReadingOrder`; service `ResearchMapService`.

**May use (application layer only):** `knowledge`. Everyone may use `shared`.

**Rules and invariants:**
- A learner's map includes only works they can read (`can_read`).
- Citation links (`work_links` table: `(citing_work_key, cited_work_key)`) are computed once per content and shared across all learners, like embeddings — they are not per-learner.
- Links, timeline, and reading order use **no model calls**; they are computed in code from extracted references.
- R2 delivery is backfilled from saved Docling output, so no re-processing of already-ingested content is needed.
- R5 relationship labeling runs in nightly batches on pairs that already cite each other or are highly similar, so cost does not scale with every possible pair.

**User stories:** US-19 (research map: timeline, citation links, one node per work), US-20 (reading order and reading-path answers), US-18 (R5 deep graph).

---

### `catalog` — Release 3

| Field | Value |
|---|---|
| **Path** | `backend/src/smart_tutor/catalog/` |
| **Release** | R3 |
| **Dependency order position** | 3rd from top — sibling of `quizzes`; above `learning`, `tutoring`, `graph` |

**Owns (PRD §9.8):** Topic catalog per content, derived from Docling headings (levels 1–2) at ingestion. A learner's catalog is the union over their active (non-archived, ready) documents; catalog entries are backfilled for all existing contents from saved Docling output before Release 3 launches.

**Key classes planned:** `TopicEntry`; service `CatalogService`.

**May use (application layer only):** `knowledge`. Everyone may use `shared`.

**Rules and invariants:**
- Topics of archived documents are never offered for recommendations.
- Catalog entries are derived from the saved Docling output (headings), so they require no additional model calls or re-extraction.

**User stories:** US-16 ("what to learn next" draws 3–5 recommendations from the topic catalog of active documents).

---

### `quizzes` — Release 3

| Field | Value |
|---|---|
| **Path** | `backend/src/smart_tutor/quizzes/` |
| **Release** | R3 |
| **Dependency order position** | 3rd from top — sibling of `catalog`; above `learning`, `tutoring`, `graph` |

**Owns (US-14):** Multiple-choice quizzes generated from selected Lesson Notes, graded in code.

**Key classes planned:** `Quiz` (with a `grade(answers)` method); service `QuizService`.

**May use (application layer only):** `learning`. Everyone may use `shared`.

**Rules and invariants:**
- The answer key is **never exposed to the client before submission**. Quizzes are stored without revealing the correct index until the learner submits answers.
- Grading happens in code (not by a model), yielding score, correct answers, explanations, and per-topic scores.
- Each quiz draws from 1–10 active notes and produces 5–10 questions with 4 options and one correct answer; the model is given one retry if the output fails code validation.

**User stories:** US-14 (generate quiz from notes; list, retake, archive; per-topic scores). US-12 prohibits one learner from seeing another's quizzes.

---

### `recommendations` — Release 3

| Field | Value |
|---|---|
| **Path** | `backend/src/smart_tutor/recommendations/` |
| **Release** | R3 |
| **Dependency order position** | 2nd from top — below `reports`; above `quizzes`, `catalog`, `learning`, `graph` |

**Owns (US-16, PRD D14):** "What should I learn next?" recommendations — 3–5 suggestions from the topic catalog of the learner's active documents, each with a subject, topic, reason, and document/page.

**Key classes planned:** `Recommendation`; service `RecommendationService`.

**May use (application layer only):** `catalog`, `quizzes`, `learning`, `graph`. Everyone may use `shared`.

**Rules and invariants:**
- Candidates come from code only: weak quiz topics (< 60%) first, then the next works in the reading order and topic-catalog entries not yet covered by learning records.
- The model only ranks and explains; it cannot introduce topics outside the candidate list — topics outside candidates are **rejected**.
- Each recommendation carries its source document and page so the learner can start a new thread directly.

**User stories:** US-16 ("start learning" opens a new thread on the recommended topic). D14 specifies the candidate selection and reading-order respect rule.

---

### `reports` — Release 3

| Field | Value |
|---|---|
| **Path** | `backend/src/smart_tutor/reports/` |
| **Release** | R3 |
| **Dependency order position** | 1st (topmost) — depends on everything below it |

**Owns (US-15, PRD §9.8):** Daily and weekly learner reports across all subjects, generated on a schedule and on demand.

**Key classes planned:** `Report`; service `ReportService`.

**May use (application layer only):** `learning`, `quizzes`, `recommendations`. Everyone may use `shared`.

**Rules and invariants:**
- No report is generated for a period without activity.
- Reports are **idempotent per `(user_id, period_type, period_start)`**: the `reports` table has a unique constraint on this triple, so a scheduled run cannot produce duplicate reports for the same period.
- Daily and weekly periods use the learner's time zone; weekly periods run Monday–Sunday.
- Scheduled reports are driven by an **hourly CronJob** (`apps/jobs`); on-demand reports can be triggered at any time.
- Report contents: topics learned, thread counts, quiz results, weak topics (< 60%), and recommendations.

**User stories:** US-15 (daily/weekly and on-demand reports; list, view, archive). US-12 prohibits one learner from accessing another's reports.

---

## Dependency map

The diagram below shows only the five later-release modules and their direct inter-module dependencies (arrows point from consumer to producer):

```mermaid
flowchart TD
    reports["reports\n(R3)"]
    recommendations["recommendations\n(R3)"]
    quizzes["quizzes\n(R3)"]
    catalog["catalog\n(R3)"]
    learning["learning\n(R1)"]
    graph["graph\n(R2/R5)"]
    knowledge["knowledge\n(R1)"]

    reports --> learning
    reports --> quizzes
    reports --> recommendations
    recommendations --> catalog
    recommendations --> quizzes
    recommendations --> learning
    recommendations --> graph
    quizzes --> learning
    catalog --> knowledge
    graph --> knowledge
```

*Later-release module dependencies. All five modules are currently empty stubs; arrows show permitted application-layer imports once built.*

---

## Current state

All five modules are **entirely empty stubs**. Every sub-package (`domain/`, `application/`, `ports/`, `adapters/`) contains only a docstring `__init__.py`. There are no domain classes, no services, no ports, and no adapters. The four-layer directory structure is in place to reserve the layout and satisfy the `import-linter` module dependency contract.

Per [AGENTS.md](../../backend/AGENTS.md): **build them only when asked**.

---

## Related pages

- [Module Structure and Import Rules](../architecture/module-layer-rules.md) — layer rules, import-linter contracts, full module dependency order
- [Data Model](../concepts/data-model.md) — `work_links`, `quizzes`, `quiz_questions`, `quiz_attempts`, and `reports` table schemas
- [Content Document Lifecycle](../concepts/content-document-lifecycle.md) — ingestion steps that produce the saved Docling output these modules consume
