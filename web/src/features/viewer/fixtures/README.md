# Seed-corpus text fixture

`seed-text.json` holds, for the first 6 pages of four seed-corpus papers (`backend/evals/seed_corpus/manifest.yaml`), the pdf.js text items of each page (string and end-of-line flag) and the chunks the ingestion worker cuts from those pages (page, `start_index`, text). `../passage.seed.test.ts` runs the viewer's matcher over every chunk; PRD §10.1 "Citation highlight" requires it to find at least 95% on their page.

**Last measured (2026-10-10):** 133 of 133 chunks found (100%): 130 by the whole chunk, 3 by its first and last words, where pypdf and pdf.js decode a math glyph differently (`⟨` vs `〈`, `↦` vs `7`).

## Sources and license

Excerpts of the papers' text, licensed **CC BY 4.0** (https://creativecommons.org/licenses/by/4.0/). The text is unmodified except for extraction (pdf.js text items; pypdf page text after the worker's cleanup and chunking).

- Shunyu Yao, Jeffrey Zhao, Dian Yu, Nan Du, Izhak Shafran, Karthik Narasimhan, Yuan Cao. *ReAct: Synergizing Reasoning and Acting in Language Models*. https://arxiv.org/abs/2210.03629v3
- Jason Wei, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Brian Ichter, Fei Xia, Ed Chi, Quoc Le, Denny Zhou. *Chain-of-Thought Prompting Elicits Reasoning in Large Language Models*. https://arxiv.org/abs/2201.11903v6
- Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao. *Reflexion: Language Agents with Verbal Reinforcement Learning*. https://arxiv.org/abs/2303.11366v4
- Akari Asai, Zeqiu Wu, Yizhong Wang, Avirup Sil, Hannaneh Hajishirzi. *Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection*. https://arxiv.org/abs/2310.11511v1

## Regenerate

With the PDFs in `data/seed_corpus/` (see `backend/evals/seed_corpus/README.md`; check each SHA-256 against the manifest):

```bash
cd backend && uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out ../data/highlight-chunks.json ../data/seed_corpus/*.pdf
cd ../web && node scripts/text-layer-fixture.mjs --chunks ../data/highlight-chunks.json --pages 6 \
  --ids react-2022=2210.03629v3,cot-2022=2201.11903v6,reflexion-2023=2303.11366v4,self-rag-2023=2310.11511v1 ../data/seed_corpus
```

Regenerate after changing the extractor, the chunker, or the page cleanup (`clean_page_text`), then run `npx vitest run src/features/viewer/passage.seed.test.ts`.
