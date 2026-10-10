import { describe, expect, it } from "vitest";
import { findPassage, matchKey, passageBoxes, type TextItem } from "./passage";

const item = (str: string, hasEOL = false, x = 0, y = 0, width = str.length * 5, height = 10): TextItem => ({ str, hasEOL, x, y, width, height });

describe("matchKey", () => {
  it("folds ligatures, joins line-end hyphens, and drops whitespace", () => {
    expect(matchKey("ﬁne exam-\nple  A-\nB").key).toBe("fineexampleA-B");
  });
  it("maps each key character back to the source", () => {
    const { key, map } = matchKey("a ﬁ b");
    expect(key).toBe("afib");
    expect(map).toEqual([0, 2, 2, 4]);
  });
  it("composes a base letter with its combining marks, as NFKC of the whole page does", () => {
    const { key, map } = matchKey("ae\u0301 b");
    expect(key).toBe("a\u00e9b");
    expect(map).toEqual([0, 1, 4]);
  });
  it("folds characters outside the BMP (math letters) without splitting their surrogate pairs", () => {
    const { key, map } = matchKey("\u{1D431} = 1");
    expect(key).toBe("x=1");
    expect(map).toEqual([0, 3, 5]);
  });
  it("keeps one map entry per key code unit for characters NFKC leaves outside the BMP", () => {
    const { key, map } = matchKey("a \u{1F600}b");
    expect(key).toBe("a\u{1F600}b");
    expect(map).toEqual([0, 2, 2, 4]);
  });
});

describe("findPassage", () => {
  const items = [item("Reasoning traces help the model in-", true), item("duce, track, and update", true), item("action plans.", true)];

  it("finds a chunk across items, hyphenation, and line breaks", () => {
    const span = findPassage(items, "help the model induce, track, and update action plans.", 0);
    expect(span).toEqual({ start: { item: 0, offset: 17 }, end: { item: 2, offset: 13 } });
  });
  it("matches whatever spacing each extractor used", () => {
    const spaced = [item("Thought"), item(" : "), item("I need to search"), item("Apple Remote", true)];
    expect(findPassage(spaced, "Thought: I need to search Apple Remote", null)).not.toBeNull();
  });
  it("start_index chooses between repeats", () => {
    const repeated = [item("Answer the question. ", false), item("Some text in between here. ", false), item("Answer the question.", true)];
    expect(findPassage(repeated, "Answer the question.", 0)?.start.item).toBe(0);
    expect(findPassage(repeated, "Answer the question.", 47)?.start.item).toBe(2);
  });
  it("falls back to the chunk's first and last words when the middle differs", () => {
    const head = "The agent first reads the question and then decides what to search for";
    const tail = "before it writes its final answer for the learner to read";
    const page = [item(`${head} [a footnote marker 1] ${tail}`, true)];
    const span = findPassage(page, `${head} ${tail}`, null);
    expect(span?.start).toEqual({ item: 0, offset: 0 });
    expect(span?.end.offset).toBe(page[0]!.str.length);
  });
  it("finds a chunk whose letters pdf.js gives decomposed or as math alphanumerics", () => {
    const page = [item("the cafe\u0301 where \u{1D431} is set", true)];
    const span = findPassage(page, "caf\u00e9 where x is", null);
    expect(span).toEqual({ start: { item: 0, offset: 4 }, end: { item: 0, offset: 21 } });
  });
  it("ends the span after the whole last character, not inside its surrogate pair or before its marks", () => {
    const math = [item("let \u{1D431}", true)];
    expect(findPassage(math, "let x", null)?.end).toEqual({ item: 0, offset: 6 });
    const accent = [item("cafe\u0301", true)];
    expect(findPassage(accent, "caf\u00e9", null)?.end).toEqual({ item: 0, offset: 5 });
  });
  it("returns null when the chunk isn't on the page", () => {
    expect(findPassage(items, "Nothing like this appears on the page at all.", 0)).toBeNull();
  });
  it("returns null for a blank chunk", () => {
    expect(findPassage(items, "  \n ", 0)).toBeNull();
  });
});

describe("passageBoxes", () => {
  it("draws one box per line, partial at the ends", () => {
    const lines = [item("aaaa bbbb", true, 10, 0, 90, 10), item("cccc", false, 10, 12, 40, 10), item(" dddd", true, 50, 12, 50, 10)];
    const boxes = passageBoxes(lines, { start: { item: 0, offset: 5 }, end: { item: 2, offset: 3 } });
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toEqual({ x: 60, y: 0, width: 40, height: 10 });
    expect(boxes[1]).toEqual({ x: 10, y: 12, width: 70, height: 10 });
  });
});
