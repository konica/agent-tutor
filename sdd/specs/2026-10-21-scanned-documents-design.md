# Scanned documents and document intelligence — Design

- Date: 2026-10-21
- Status: draft, for review
- Release: **2** (the product owner moved it from Release 1)
- PRD: D26 (page text with `pypdf`), the "no scanned PDFs" out-of-scope line, §9.7 (Release 2 structured extraction), US-4b (document viewer and highlight); a new story **US-21** is added with this work
- ADRs: 0005 (`pypdf` instead of Docling; to be superseded in part), 0008 (chunking and the "no text layer" rule), 0011 (per-learner contents)

## 1. Why

- **Scanned PDFs fail today.** A PDF averaging under 50 characters per page fails with "No text layer (scanned PDFs are not supported yet)". Learners hold scanned books, lecture handouts, and phone photos made into PDFs.
- **Digital extraction is plain.** `pypdf` plain mode gives no reading order across columns, mixes figure labels, headers and footers into body text, and flattens tables (ADR 0008 recorded this).
- **The product owner wants document intelligence** (OCR, layout detection, reading order, tables). The AI engineer, ML engineer, data scientist, and business analyst weighed the options in the grilling of 2026-10-21; this design is the result.

## 2. Outcome and success

- A learner uploads a scanned or phone-photo PDF in English or Vietnamese and gets a ready document. Chat answers cite it, and a citation opens the PDF with the passage highlighted.
- Digital PDFs behave as today until Release 2b (section 8).
- A scanned document is marked, with low-confidence pages visible, so a learner knows the text may contain errors.
- **Quality is judged from learner feedback, not a benchmark.** The product owner decided to start with Docling and see how well it works. If it works poorly, the product owner will consider the advanced techniques (section 5) later.

Not in scope:
- **A bake-off or labelled evaluation set** (decided 2026-10-21). A handful of real sample pages are used as smoke tests only (section 9).
- **PaddleOCR, a separate layout or reading-order engine, tier escalation, and Landing AI.** They are deferred (section 5), but the job API is designed so they can be added without a worker change.
- **Handwriting.** If it extracts, fine; low confidence shows a warning.
- **Word-level boxes.** The first version stores line boxes.
- **Sending learner documents to any other vendor.**
- **An agentic OCR loop.** It comes later behind the same job API.
- A trust-boundary ADR for the GPU host and GPU-outage handling. The product owner set both aside; this design assumes the host is reachable. The repo rules still hold: no tokens in prompts, logs, or traces, and no learner id is sent to the OCR service.

## 3. Decisions made

| # | Decision |
|---|---|
| Scanned scope | Printed text from scanners and phone cameras, including mixed PDFs (decided per page). Languages: English and Vietnamese are the acceptance languages; the language is detected, not chosen. |
| Limits | A scanned PDF is capped at **200 pages**; digital PDFs keep 500 pages and 50 MB. Over the cap, the file is rejected with a specific reason. Only pages needing OCR go to the OCR service; digital pages stay on `pypdf`. |
| Boxes | Option B: **boxes are stored in the backend** for OCR'd pages, for the highlight (section 6). Digital pages keep browser-side text matching. |
| Engine | **Docling** (layout, reading order, tables, OCR) in the OCR service. The OCR backend is set explicitly, with languages `eng` and `vie`; the first default is Tesseract and it is a configuration value, changeable without a worker release. |
| Hosting | One **rented GPU box** (RTX A4000 16 GB, Ubuntu 22.04, k3s plus the NVIDIA container toolkit), reached over SSH or a tunnel, running a **separate Helm chart**. One box is enough while Smart Tutor is in development. |
| Quality loop | Learner feedback and per-document OCR confidence (section 9) decide whether the advanced techniques are needed. |

## 4. Architecture

```
upload ─► S3 ─► SQS ─► worker (AWS)
                         │ pypdf on every page; page classifier flags pages that need OCR
                         ├─ digital pages: unchanged
                         └─ flagged pages ─► OcrClient ─HTTP job API (tunnel)─► OCR chart (GPU host)
                                                                              └─ Docling (layout + reading order + OCR)
```

- **Worker.** Stays small. It keeps `pypdf` for digital pages and gains one `OcrClient` port with an HTTP adapter. Engine changes never need a worker release.
- **OCR chart.** Everything new lives here behind one job API: submit pages (images and the page range), poll, fetch the result. The result is the page's lines with text, box, and confidence, plus the engine and its version. The chart owns the line and box output and the coordinate conversion. A second engine, tiering, or an agentic loop can be added later behind this API.
- **Docling in the chart, not the worker.** Docling's own OCR is slow on CPU and heavy in memory (closed investigation #27), and the worker's filesystem is read-only. Running it on the rented box avoids both.
- **Page classifier.** A page needs OCR when its text layer is missing or too thin. A missed scan means a silent empty answer, so it errs toward sending the page.
- **Capacity.** One scanned job runs on the GPU at a time; the queue absorbs bursts. Revisit before real launch traffic.
- **Failure.** The worker retries through the existing attempt counter (3). No other vendor is used as a fallback.

## 5. Deferred: advanced techniques

If learner feedback shows Docling is not good enough, the product owner will pick from these; none is built now.

- **PaddleOCR** with PP-StructureV3 layout detection and reading order, with page-level escalation from Docling on measured signals (low confidence, multi-column or table-heavy layout, poor image quality).
- **Landing AI** by API key. It is a hosted API outside infrastructure we control, so enabling it needs a PRD and ADR change covering learner consent, zero data retention, and region. Its boxes are chunk-level, so highlights would be region-level and flagged as approximate unless aligned back to line boxes.
- **An agentic loop** (crop regions, recognise, verify, reconcile with OCR words).
- A labelled evaluation set and thresholds in `backend/evals/thresholds.yaml`, if the product owner wants to measure instead of judging from feedback.

## 6. Boxes and the highlight

Today chunks store only the page and `start_index`; the browser matches chunk text against the pdf.js text layer. A scanned page has none, so:

- `pages.json` in S3 gains, per OCR'd page, the page size and a list of lines. Each line has its text, a box in **normalized 0–1 page coordinates with rotation already applied**, and a confidence score.
- Each chunk keeps its `start_index`. The API maps the chunk's character span to the lines it covers and returns ready-to-draw rectangles with the citation.
- The viewer draws those rectangles for OCR'd pages and keeps the existing text matching for digital ones.
- Docling's coordinate origin and units, and the image DPI, are converted once inside the OCR chart, so the viewer only sees normalized boxes.
- Chunking is unchanged: still per page, 1000/200, so a chunk keeps one physical page.

## 7. What the learner sees

- Document status while OCR runs: "Reading scanned pages (n of N)".
- A **"Scanned — text may contain errors"** badge when any page falls below the confidence threshold, with the low-confidence pages identifiable in the viewer.
- Specific rejection reasons: over the 200-page scanned cap, or unreadable.
- Documents that failed earlier with "No text layer" get a **Retry** that uses the new path. Existing digital documents are unchanged.
- A **"Text looks wrong"** action on a scanned document (section 9).

## 8. Phasing

- **2a, scanned support.** Everything above, with digital PDFs unchanged.
- **2b, better digital extraction.** Digital pages that look complex are routed through the same Docling pipeline and adopt the box model. Existing documents are re-processed only on request, because changed chunk text breaks the browser highlight and shifts `start_index`. 2b is decided after 2a feedback.

## 9. Quality: feedback instead of a bake-off

- **Smoke tests.** A few real English and Vietnamese pages (a clean scan, a phone photo, a two-column page) run through the OCR chart in a test that checks the job API contract and that the boxes land on the right page area. This proves the pipeline works; it does not rank engines.
- **Signals kept per document:** the engine and version, the mean and minimum page confidence, the share of pages below the badge threshold, and the page count. They go to Langfuse and to the document record, so the product owner can see how often the badge shows.
- **Learner feedback.** "Text looks wrong" on a scanned document records the document and page, with an optional note, and no document text. The decline-log privacy rule does not change.
- **Review.** The product owner reads the signals and feedback after launch of 2a and decides whether to open the deferred work in section 5.

## 10. Evidence behind the choices

- **Textract has no Vietnamese**; Azure supports it but sends documents to another cloud; Google's support is unconfirmed. Landing AI and Mistral OCR give chunk- or paragraph-level boxes at best. Vision-language models alone give unreliable boxes and can invent text.
- **Character accuracy does not predict RAG quality** (arXiv 2605.00911, kept in `backend/evals/seed_corpus/papers/`). Reading order, multi-column pages, and tables cause the damage. This is why Docling's layout and reading order, not plain OCR, is the starting point.
- **No independent Vietnamese or phone-photo benchmark exists** for any engine we found. That is the main risk of skipping the bake-off, accepted by the product owner and handled by the feedback loop.
- Surya and Marker weights need a paid licence above $5M funding or revenue, so they are not candidates.

## 11. Documents to change when this is built

- **PRD:** remove "scanned PDFs without a text layer" from out of scope; add US-21; update D26, the failure messages, the data model (`pages.json` lines and boxes, engine and confidence per document), and Release 2; bump the version in the status line.
- **ADR 0025:** Docling-based document intelligence on a rented GPU host (supersedes 0005 in part). **ADR 0026:** the box model for OCR'd pages.
- **Spec:** `2026-10-02-project-structure-design.md` gains the `OcrClient` port and the OCR chart under `deploy/helm/`.

## 12. Risks

- **Vietnamese and phone-photo accuracy is unverified.** Mitigated by the badge, the confidence signals, and learner feedback; the deferred work in section 5 is the escape hatch.
- **One GPU, no failover.** Accepted for development; revisit before launch.
- **Digital highlights could regress** if 2b changes chunk text; mitigated by re-processing existing documents only on request.

## 13. Next steps

1. Review this doc.
2. Slice into GitHub sub-issues with `to-tickets`.
3. Write the implementation plan with `writing-plans` only after the tickets exist.
