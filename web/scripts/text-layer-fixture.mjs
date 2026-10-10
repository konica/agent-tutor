// The pdf.js text items of seed-corpus PDFs plus the worker's chunks, for passage.seed.test.ts (see fixtures/README.md).
// Usage: node scripts/text-layer-fixture.mjs --chunks chunks.json --pages 6 --ids react-2022=2210.03629v3,... <pdf dir>
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";

const OUT = new URL("../src/features/viewer/fixtures/seed-text.json", import.meta.url);

const { values, positionals } = parseArgs({
  options: { chunks: { type: "string" }, pages: { type: "string", default: "6" }, ids: { type: "string" } },
  allowPositionals: true,
});
if (!values.chunks || !values.ids || positionals.length !== 1) {
  console.error("Usage: node scripts/text-layer-fixture.mjs --chunks chunks.json --pages 6 --ids id=stem,... <pdf dir>");
  process.exit(2);
}
const [dir] = positionals;
const pages = Number(values.pages);
const chunks = JSON.parse(readFileSync(values.chunks, "utf8"));

const documents = [];
for (const pair of values.ids.split(",")) {
  const [id, stem] = pair.split("=");
  if (!chunks[stem]) throw new Error(`no chunks for ${stem} in ${values.chunks}`);
  const task = getDocument({ data: new Uint8Array(readFileSync(join(dir, `${stem}.pdf`))), useSystemFonts: true });
  const pdf = await task.promise;
  const layer = [];
  for (let n = 1; n <= Math.min(pages, pdf.numPages); n++) {
    const content = await (await pdf.getPage(n)).getTextContent();
    layer.push({ page: n, items: content.items.filter((i) => "str" in i).map((i) => [i.str, i.hasEOL]) });
  }
  await task.destroy();
  documents.push({ id, pages: layer, chunks: chunks[stem] });
}
writeFileSync(OUT, JSON.stringify({ documents }));
console.log(`wrote ${documents.length} documents to ${fileURLToPath(OUT)}`);
