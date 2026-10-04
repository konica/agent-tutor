# 0008. Chunk page text with a LangChain document transformer

- Status: accepted
- Date: 2026-10-04

## Context

ADR 0005 reads each PDF page with `pypdf` into a LangChain `Document` and splits pages with `RecursiveCharacterTextSplitter`, but left the splitter settings, page boundaries, empty pages, and reference lists open (wayfinder ticket #30). Many chunking methods exist (semantic, heading-aware, token-based); the product owner chose the simplest standard splitter as the starting point, with a design that lets other methods be added later without changing existing code.

A probe of six arXiv papers (Attention, BERT, ResNet, VAE, GPT-3, an LLM survey) with `pypdf` 6.19 in plain mode showed:

- Page text has a median of 3,100–6,000 characters; no page was empty; figure-only pages hold ~100 characters.
- `pypdf` emits no `"\n\n"`: only a `"\n"` at every visual line end.
- Line-end hyphenation is frequent (up to 2,297 in one paper) and ligatures (ﬁ, ﬂ) are common.
- Reference lists hold 11–41% of the text, and 4 of 6 papers have appendices after them.
- Two-column pages came out in reading order; figure labels are mixed into the body text.
- Printed page labels differed from the physical index in one paper only.

## Decision

- **Splitter:** `RecursiveCharacterTextSplitter(separators=["\n\n", "\n", ". ", " ", ""], chunk_size=512, chunk_overlap=50, length_function=len, is_separator_regex=False)` from `langchain_text_splitters`. Sizes are **characters**; the values live in settings.
- **One page per chunk:** the splitter runs on each page `Document` separately, so every chunk keeps exactly one `page`: the physical, 1-based page index.
- **Nothing is dropped:** reference lists, front matter, and appendices are chunked like body text. Release 2's structured extraction is the tool for finding reference lists.
- **Text:** `pypdf` plain mode (not layout mode). `contents/<sha256>.pages.json` keeps the **raw** page text. Before splitting, the adapter applies NFKC normalization, joins line-end hyphens between lowercase letters, and removes control characters.
- **Empty and short pages:** a page with no non-whitespace text yields no chunks; short pages are kept. A PDF fails with "No text layer" when its pages average fewer than 50 non-whitespace characters.
- **Extension point:** `IngestionService` (application) receives a `langchain_core` `BaseDocumentTransformer` and a chunker id, and passes it the list of all page `Document`s. A registry in `knowledge.adapters` builds the transformer from settings (`chunking.method = "recursive_character"` plus its parameters). A new method is one new LangChain splitter (or thin subclass) and one registry entry; the service does not change. The service validates every method's output: each chunk has an integer `metadata["page"]`, non-empty text, and at most 8,192 characters (the embedding limit); it assigns `seq` in output order.
- **Chunker identity:** `contents.chunker` records the method, parameters, and a version (e.g. `recursive_character:512/50:v1`); `chunks.seq` orders chunks within a content (unique per content). Changing the settings affects new contents only.

## Consequences

- No custom chunker port: the seam is LangChain's own interface (see ADR 0006). `langchain_text_splitters` stays importable only from `knowledge.adapters`; `langchain_core` is allowed everywhere.
- 512-character chunks give about 6–12 chunks per page, so more embedding calls per content; ingestion targets (PRD §11) still hold with parallel calls. Search keeps k = 5, about 2,500 characters of evidence per answer; the M1 retrieval eval decides whether the size or k must change.
- `"\n\n"` never fires on `pypdf` text, so chunks break at line ends or sentence ends (`". "`).
- Sentences that cross a page break are cut; the overlap only works within a page.
- Re-chunking existing contents (from saved `pages.json`, no PDF needed) is a later ticket, built when a second method or new settings need it; `contents.chunker` shows which contents are stale.
- Reference-list chunks can be retrieved for keyword-heavy questions; the M1 retrieval eval measures it.
