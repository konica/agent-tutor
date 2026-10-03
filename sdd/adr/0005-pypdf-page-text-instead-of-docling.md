# 0005. Extract PDF page text with `pypdf` and LangChain instead of Docling in Release 1

- Status: accepted
- Date: 2026-10-03

## Context

PRD v2.2 extracted every new content with Docling and saved its structured output, so Release 2 (reference lists for the research map) and Release 3 (section headings for the topic catalog) would need no reprocessing. Docling brings PyTorch and layout and table models into the worker: a multi-gigabyte image, about a second per page on CPU, and an M0 benchmark before work could start (research on wayfinder ticket #27). Release 1 itself only needs page text for chunks and page numbers for citations.

The product owner chose a LangChain PDF loader instead. LangChain's classic `PyPDFLoader` lives in `langchain-community`, which was sunset in May 2026 and archived in June 2026 (langchain-ai/langchain-community#674), and no standalone replacement package exists. LangChain's current guide ("Load and split a PDF") reads pages with `pypdf` into `langchain_core` `Document`s and splits them with `RecursiveCharacterTextSplitter`.

## Decision

- Release 1 reads PDFs with **`pypdf`**, one LangChain `Document` per page with its page number in metadata, following LangChain's guide. The first-pages step uses the same reader.
- Chunks come from **`RecursiveCharacterTextSplitter`** (`langchain-text-splitters`) per page, so every chunk keeps its page.
- The worker saves the page text as `contents/<sha256>.pages.json` (`contents.text_key`), replacing the saved Docling JSON.
- No OCR: a PDF without extractable text fails with a reason.
- Reference lists and section headings move to a **structured-extraction step added in Release 2**, backfilled from the stored PDFs of referenced contents. The extractor (Docling or another) is chosen then.
- The reader sits behind the `PdfExtractor` port in `knowledge.adapters`; `pypdf` and `langchain_text_splitters` are importable only there (import-linter).
- Do not depend on `langchain-community`.

## Consequences

- The `ingest` extra is `pypdf` and `langchain-text-splitters`; the worker image needs no PyTorch, and M0 drops the Docling benchmark.
- Multi-column pages, tables, and formulas may extract in a poor reading order. The M1 retrieval and filtered-recall evals measure the effect.
- Scanned PDFs are not supported in Release 1.
- Release 2 must reprocess referenced contents once. Their PDFs stay in S3 Standard; only contents linked again after moving to Glacier need a restore first.
- Partly supersedes ADR 0001 (the `ingest` extra no longer holds Docling) and ADR 0002 (a content holds saved page text, not saved Docling output).
