// Finds a cited chunk on the pdf.js text layer of its page (PRD §9.3 step 5). The chunk was cut from pypdf's text after
// the chunking cleanup (NFKC, joined line-end hyphens); pdf.js splits and spaces the same words differently, so both
// sides are compared in one key form: the same cleanup, then no whitespace at all (the extreme of collapsing it).

// One pdf.js text-content item; the box is in CSS px at zoom 100%, origin top-left of the page.
export type TextItem = { str: string; hasEOL: boolean; x: number; y: number; width: number; height: number };
// `end` is exclusive.
export type PassageSpan = { start: { item: number; offset: number }; end: { item: number; offset: number } };
export type Box = { x: number; y: number; width: number; height: number };

const EDGE = 40; // key characters compared at each end when the whole chunk isn't found
const SPAN_SLACK = 0.3; // a head-to-tail match may be 30% shorter or longer than the chunk

// `map[i]` is the index in `source` of `key[i]`.
export function matchKey(source: string): { key: string; map: number[] } {
  // 1. NFKC per source character, remembering where each output character came from.
  const chars: string[] = [];
  const from: number[] = [];
  for (let i = 0; i < source.length; i++) {
    for (const c of source[i]!.normalize("NFKC")) {
      chars.push(c);
      from.push(i);
    }
  }
  // 2. Join words hyphenated across lines (lowercase on both sides), as clean_page_text does; 3. drop whitespace and
  // control characters.
  const key: string[] = [];
  const map: number[] = [];
  for (let i = 0; i < chars.length; i++) {
    const c = chars[i]!;
    if (c === "-" && chars[i + 1] === "\n" && /[a-z]/.test(chars[i - 1] ?? "") && /[a-z]/.test(chars[i + 2] ?? "")) {
      i++; // skip the hyphen and the line break
      continue;
    }
    if (/\s/.test(c) || /\p{Cc}/u.test(c)) continue;
    key.push(c);
    map.push(from[i]!);
  }
  return { key: key.join(""), map };
}

function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  for (let i = haystack.indexOf(needle); i >= 0; i = haystack.indexOf(needle, i + 1)) found.push(i);
  return found;
}

// start_index counts characters of the cleaned text with its whitespace; the key has none, so compare positions by
// their share of the page rather than as raw offsets. Null start_index: no preference (the first match wins).
function targetOf(startIndex: number | null, keyLength: number, sourceLength: number): number | null {
  return startIndex === null ? null : (startIndex / Math.max(1, sourceLength)) * keyLength;
}

// Candidates ordered nearest-first to the target (stable: equal distances keep page order).
function byNearness(candidates: number[], target: number | null): number[] {
  return target === null ? candidates : [...candidates].sort((a, b) => Math.abs(a - target) - Math.abs(b - target));
}

export function findPassage(items: Pick<TextItem, "str" | "hasEOL">[], text: string, startIndex: number | null): PassageSpan | null {
  // The page as the text layer reads it, and which item each character belongs to.
  let source = "";
  const owner: { item: number; offset: number }[] = [];
  items.forEach((it, index) => {
    for (let o = 0; o < it.str.length; o++) owner.push({ item: index, offset: o });
    source += it.str;
    if (it.hasEOL) {
      owner.push({ item: index, offset: it.str.length });
      source += "\n";
    }
  });
  const page = matchKey(source);
  const chunk = matchKey(text).key;
  if (!chunk) return null;

  const target = targetOf(startIndex, page.key.length, source.length);
  let start: number | undefined = byNearness(occurrences(page.key, chunk), target)[0];
  let end = start === undefined ? undefined : start + chunk.length;
  if (start === undefined && chunk.length >= 2 * EDGE) {
    const head = chunk.slice(0, EDGE);
    const tail = chunk.slice(-EDGE);
    for (const h of byNearness(occurrences(page.key, head), target)) {
      const t = page.key.indexOf(tail, h + EDGE);
      if (t < 0) continue;
      const length = t + EDGE - h;
      if (Math.abs(length - chunk.length) <= chunk.length * SPAN_SLACK) {
        start = h;
        end = t + EDGE;
        break;
      }
    }
  }
  if (start === undefined || end === undefined) return null;
  const first = owner[page.map[start]!]!;
  const last = owner[page.map[end - 1]!]!;
  return { start: first, end: { item: last.item, offset: last.offset + 1 } };
}

// One box per text line: the items' pieces inside the span, merged when their vertical centers are within half a line
// height of each other, top to bottom.
export function passageBoxes(items: TextItem[], span: PassageSpan): Box[] {
  const pieces: Box[] = [];
  for (let i = span.start.item; i <= span.end.item; i++) {
    const it = items[i]!;
    const length = it.str.length;
    if (length === 0 || it.width <= 0) continue;
    const from = i === span.start.item ? Math.min(span.start.offset, length) : 0;
    const to = i === span.end.item ? Math.min(span.end.offset, length) : length;
    if (to <= from) continue;
    pieces.push({ x: it.x + (it.width * from) / length, y: it.y, width: (it.width * (to - from)) / length, height: it.height });
  }
  const lines: Box[] = [];
  for (const p of pieces) {
    const line = lines.find((l) => Math.abs(l.y + l.height / 2 - (p.y + p.height / 2)) < Math.max(l.height, p.height) / 2);
    if (!line) {
      lines.push({ ...p });
      continue;
    }
    const right = Math.max(line.x + line.width, p.x + p.width);
    const bottom = Math.max(line.y + line.height, p.y + p.height);
    line.x = Math.min(line.x, p.x);
    line.y = Math.min(line.y, p.y);
    line.width = right - line.x;
    line.height = bottom - line.y;
  }
  return lines.sort((a, b) => a.y - b.y || a.x - b.x);
}
