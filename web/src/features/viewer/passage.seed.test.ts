import { describe, expect, it } from "vitest";
import fixture from "./fixtures/seed-text.json";
import { findPassage } from "./passage";

type Doc = {
  id: string;
  pages: { page: number; items: [string, boolean][] }[];
  chunks: { page: number; start_index: number | null; text: string }[];
};

// PRD §10.1 "Citation highlight": ≥ 95% of seed-corpus chunks are found on their page by the viewer's matcher.
describe("the matcher on the seed corpus", () => {
  const docs = (fixture as { documents: Doc[] }).documents;
  const results = docs.flatMap((doc) =>
    doc.chunks.map((chunk) => {
      const page = doc.pages.find((p) => p.page === chunk.page)!;
      const items = page.items.map(([str, hasEOL]) => ({ str, hasEOL }));
      return { doc: doc.id, page: chunk.page, found: findPassage(items, chunk.text, chunk.start_index) !== null };
    }),
  );

  it("has chunks from every document", () => {
    expect(new Set(results.map((r) => r.doc)).size).toBe(docs.length);
    expect(results.length).toBeGreaterThan(100);
  });

  it("finds at least 95% of chunks on their page", () => {
    const missed = results.filter((r) => !r.found).map((r) => `${r.doc} p${r.page}`);
    const rate = (results.length - missed.length) / results.length;
    expect(rate, `missed: ${missed.join(", ")}`).toBeGreaterThanOrEqual(0.95);
  });
});
