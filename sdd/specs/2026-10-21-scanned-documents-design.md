# Scanned documents and document intelligence — Design

- Date: 2026-10-21
- Status: draft, for review
- Release: **2** (the product owner moved it from Release 1)
- PRD: D26 (page text with `pypdf`), the "no scanned PDFs" out-of-scope line, §9.7 (Release 2 structured extraction), US-4b (document viewer and highlight)
- ADRs: 0005 (`pypdf` instead of Docling; to be superseded in part), 0008 (chunking and the "no text layer" rule), 0011 (per-learner contents)

## 1. Why

- **Scanned PDFs fail today.** A PDF averaging under 50 characters per page fails with "No text layer (scanned PDFs are not supported yet)". Learners hold scanned books, lecture handouts, and phone photos made into PDFs.
- **Digital extraction is plain.** `pypdf` plain mode gives no reading order across columns, mixes figure labels, headers and footers into body text, and flattens tables (ADR 0008 recorded this).
- **The product owner wants document intelligence** (OCR, layout detection, reading order, tables) to fix both, and asked the AI engineer, ML engineer, data scientist, and business analyst to weigh the options. This design is the result of the grilling of 2026-10-21.

## 2. Outcome and success

- A learner uploads a scanned or phone-photo PDF in English or Vietnamese and gets a ready document. Chat answers cite it, and a citation opens the PDF with the passage highlighted.
- Digital PDFs behave as today until Release 2b (section 8).
- A scanned document is marked, with low-confidence pages visible, so a learner knows the text may contain errors.
- An OCR engine is chosen from measured scores on our own pages, not from vendor claims.

Not in scope:
- **Handwriting.** If it extracts, fine; low confidence shows a warning.
- **Word-level boxes.** The first version stores line boxes.
- **Sending learner documents to any other vendor.** Landing AI (tier 3) gets an adapter slot only (section 5).
- **Native-cloud OCR hosting.** The OCR service runs on a rented GPU host.
- **An agentic OCR loop.** It comes later behind the same job API (section 4).
- A trust-boundary ADR for the GPU host and GPU-outage handling. The product owner set both aside; this design assumes the host is reachable. The repo rules still hold: no tokens in prompts, logs, or traces, and no learner id is sent to the OCR service.

## 3. Decisions made in the grilling

| # | Decision |
|---|---|
| Scanned scope | Printed text from scanners and phone cameras, including mixed PDFs (decided per page). Languages: English and Vietnamese are the acceptance languages; the language is detected, not chosen. |
| Limits | A scanned PDF is capped at **200 pages**; digital PDFs keep 500 pages and 50 MB. Over the cap, the file is rejected with a specific reason. Pages needing OCR go to the paid or GPU tier; digital pages stay on `pypdf`. |
| Boxes | Option B: **boxes are stored in the backend** for OCR'd pages, for the highlight (section 6). Digital pages keep browser-side text matching. |
| Tiers | Tier 1 **Docling** for simple pages; tier 2 **PaddleOCR** with layout detection and reading order for complex pages; tier 3 **Landing AI** by API key, later. |
| Hosting | One **rented GPU box** (RTX A4000 16 GB, Ubuntu 22.04, k3s plus the NVIDIA container toolkit), reached over SSH or a tunnel, running a **separate Helm chart**. One box is enough while Smart Tutor is in development. |
| Engine choice | A **bake-off** on about 150 labelled pages decides the tier 1 OCR backend and the escalation thresholds (section 9). |

## 4. Architecture

```
upload ─► S3 ─► SQS ─► worker (AWS)
                         │ pypdf on every page; page classifier flags pages that need OCR
                         ├─ digital pages: unchanged
                         └─ flagged pages ─► OcrClient ─HTTP job API (tunnel)─► OCR chart (GPU host)
                                                                              ├─ tier 1: Docling (CPU)
                                                                              ├─ tier 2: PaddleOCR + layout + reading order (GPU)
                                                                              └─ tier 3: Landing AI adapter (disabled)
```

- **Worker.** Stays small. It keeps `pypdf` for digital pages and gains one `OcrClient` port with an HTTP adapter. Engine changes never need a worker release.
- **OCR chart.** Everything new lives here behind one job API: submit pages (images and the page range), poll, fetch the result. The result is the page's lines with text, box, and confidence, plus the tier used. The chart owns the page-quality signals, the escalation rule, and the line and box output. An agentic loop (crop regions, recognise, verify, reconcile with OCR words) can be added later behind this API.
- **Page classifier.** A page needs OCR when its text layer is missing or too thin. The recall target is at least 0.98, because a missed scan means a silent empty answer.
- **Escalation.** Tier 1 runs first. A page moves to tier 2 on measured evidence: low OCR confidence, multi-column or table-heavy layout, a failed reading-order check, or a poor image-quality score. The thresholds come from the bake-off. The learner never chooses a tier.
- **Capacity.** One scanned job runs on the GPU at a time. Docling can use the 12 CPU cores in parallel. The queue absorbs bursts; the bake-off reports pages per minute so the queue timeouts can be set. Revisit before real launch traffic.
- **Failure.** The worker retries through the existing attempt counter (3). No other vendor is used as a fallback.

## 5. Tier 3: Landing AI

- Build **only the adapter slot**, disabled by default, with its API key read from the secrets store.
- Enabling it needs a PRD and ADR change covering learner consent, zero data retention, and region, because it is a hosted API outside infrastructure we control.
- Its boxes are chunk-level, so highlights on those pages would be region-level and flagged as approximate unless aligned back to word or line boxes from tier 1 or 2.

## 6. Boxes and the highlight

Today chunks store only the page and `start_index`; the browser matches chunk text against the pdf.js text layer. A scanned page has none, so:

- `pages.json` in S3 gains, per OCR'd page, the page size and a list of lines. Each line has its text, a box in **normalized 0–1 page coordinates with rotation already applied**, and a confidence score.
- Each chunk keeps its `start_index`. The API maps the chunk's character span to the lines it covers and returns ready-to-draw rectangles with the citation.
- The viewer draws those rectangles for OCR'd pages and keeps the existing text matching for digital ones.
- Docling's and PaddleOCR's coordinate origin and units, and the image DPI, are converted once inside the OCR chart, so the viewer only sees normalized boxes.
- Chunking is unchanged: still per page, 1000/200, so a chunk keeps one physical page.

## 7. What the learner sees

- Document status while OCR runs: "Reading scanned pages (n of N)".
- A **"Scanned — text may contain errors"** badge when any page falls below the confidence threshold, with the low-confidence pages identifiable in the viewer.
- Specific rejection reasons: over the 200-page scanned cap, or unreadable.
- Documents that failed earlier with "No text layer" get a **Retry** that uses the new path. Existing digital documents are unchanged.
- The decline-log and privacy rules do not change.

## 8. Phasing

- **2a, scanned support.** Everything above, with digital PDFs unchanged.
- **2b, better digital extraction.** Digital pages that look complex are routed through the same Docling and PaddleOCR pipeline and adopt the box model. This needs its own bake-off for the "complex digital page" signals. Existing documents are re-processed only on request, because changed chunk text breaks the browser highlight and shifts `start_index`.

## 9. Evaluation (the bake-off)

It runs **before the implementation plan**, and its first ticket sets the tier 1 and tier 2 thresholds. Gates live in `backend/evals/thresholds.yaml`.

**Dataset (about 150 pages).** 60 English and 40 Vietnamese born-digital pages, including multi-column, table, formula, and figure pages. They are rasterised at 150–200 dpi and degraded by script (rotation, blur, JPEG compression, noise, low contrast, shadow, perspective) at three severities. Add 20–30 real phone photos with hand-corrected text. Ground truth for synthetic pages is the PDF text layer with word boxes; a 20-page dev split is kept apart from the frozen test split.

**Candidates.** Docling with Tesseract (`eng+vie`), with RapidOCR (PP-OCRv6), and with EasyOCR (`vi`); PaddleOCR directly (PP-StructureV3, and PaddleOCR-VL if the card allows); current `pypdf` as the baseline; Azure Read as a ceiling reference only. First task: confirm the engines run on the A4000 (a Pascal-class card such as the P40 was rejected because current serving stacks may not support it; verify on the real box).

**Starting gates** (proposals, recalibrated after the first run):

| Metric | Starting gate |
|---|---|
| Character error rate, clean English | ≤ 2% |
| Character error rate, clean Vietnamese (diacritic-aware; also report with diacritics stripped) | ≤ 4% |
| Character error rate, degraded scans | ≤ 8% |
| Reading-order accuracy, multi-column pages | ≥ 0.90 |
| Table accuracy (TEDS or cell F1) | ≥ 0.80 |
| Retrieval recall@5, OCR text vs ground-truth text (our chunker) | ≤ 5 points below (≤ 10 on degraded pages) |
| Citation-highlight overlap with ground-truth boxes | median IoU ≥ 0.5; ≥ 90% of citations above 0.3 |
| "Needs OCR" page classifier | recall ≥ 0.98; precision ≥ 0.90 |

Also run about 30 end-to-end questions, including pages with tables and struck-through text, because a character error rate alone misses those failures. Report per language and per degradation level; the pass or fail decision rests on the degraded-English and Vietnamese slices. Record cost, latency, and pages per minute per engine.

## 10. Evidence behind the choices

- **Textract has no Vietnamese** (its language list is English, French, German, Italian, Portuguese, Spanish). Azure Document Intelligence supports Vietnamese for printed text but sends documents to another cloud. Google's Vietnamese support is unconfirmed. Landing AI and Mistral OCR give chunk- or paragraph-level boxes at best, which is too coarse for exact highlights. Vision-language models alone give unreliable boxes and can invent text.
- **Character accuracy does not predict RAG quality** (arXiv 2605.00911, the paper kept in `backend/evals/seed_corpus/papers/`). Reading order, multi-column pages, and tables cause the damage, and the model cannot repair them afterwards.
- **No independent Vietnamese or phone-photo benchmark exists** for any engine we found, so the bake-off is required.
- Azure and Google prices came from third-party or snippet sources; confirm before an ADR cites them. Surya and Marker weights need a paid licence above $5M funding or revenue, so they are not core candidates.

## 11. Documents to change when this is built

- **PRD:** remove "scanned PDFs without a text layer" from out of scope; update D26, the failure messages, the data model (`pages.json` lines and boxes, OCR tier and confidence per document), and Release 2; bump the version in the status line.
- **ADR 0025:** tiered document intelligence on a rented GPU host (supersedes 0005 in part). **ADR 0026:** the box model for OCR'd pages.
- **Spec:** `2026-10-02-project-structure-design.md` gains the `OcrClient` port and the OCR chart under `deploy/helm/`.

## 12. Risks

- **Vietnamese accuracy is unverified** for every engine; mitigated by the bake-off.
- **One GPU, no failover.** Accepted for development; revisit before launch.
- **Tier 3 breaks the "infrastructure we control" posture** if enabled; kept off until the PRD and ADR change.
- **Digital highlights could regress** if 2b changes chunk text; mitigated by routing only on request for existing documents.

## 13. Next steps

1. Review this doc.
2. Slice into GitHub sub-issues with `to-tickets`; the bake-off is the first ticket.
3. Write the implementation plan with `writing-plans` only after the tickets exist.
