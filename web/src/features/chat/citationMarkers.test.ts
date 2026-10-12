import { describe, expect, it } from "vitest";

import { splitMarkers } from "./citationMarkers";

const joined = (text: string) =>
  splitMarkers(text)
    .map((p) => p.text)
    .join("");

describe("splitMarkers", () => {
  it("keeps text without markers as one piece", () => {
    expect(splitMarkers("No sources here.")).toEqual([{ text: "No sources here." }]);
  });

  it("makes a single marker one piece, brackets included", () => {
    expect(splitMarkers("It weighs tokens [1].")).toEqual([{ text: "It weighs tokens " }, { text: "[1]", n: 1 }, { text: "." }]);
  });

  it("splits a group into one piece per number", () => {
    expect(splitMarkers("A [1, 2] B")).toEqual([
      { text: "A [" },
      { text: "1", n: 1 },
      { text: ", " },
      { text: "2", n: 2 },
      { text: "] B" },
    ]);
  });

  it("reads ranges with a hyphen or an en dash, linking the numbers shown", () => {
    expect(splitMarkers("[1-3]")).toEqual([{ text: "[" }, { text: "1", n: 1 }, { text: "-" }, { text: "3", n: 3 }, { text: "]" }]);
    expect(splitMarkers("[1 – 3]")).toEqual([
      { text: "[" },
      { text: "1", n: 1 },
      { text: " – " },
      { text: "3", n: 3 },
      { text: "]" },
    ]);
  });

  it("reads adjacent markers separately", () => {
    expect(splitMarkers("[1][2]")).toEqual([
      { text: "[1]", n: 1 },
      { text: "[2]", n: 2 },
    ]);
  });

  it("reads a leading zero as the backend does", () => {
    expect(splitMarkers("[01]")).toEqual([{ text: "[01]", n: 1 }]);
  });

  it("leaves brackets that aren't the backend's marker forms as text", () => {
    for (const text of ["[a]", "[]", "[1,]", "[ 1]", "[1 ]", "[1;2]", "[-1]"]) {
      expect(splitMarkers(text)).toEqual([{ text }]);
    }
  });

  it("keeps the text unchanged when the pieces are joined", () => {
    const text = "x[0] then [2, 4-5] and [3–1] <b>[1]</b>\n[9]";
    expect(joined(text)).toBe(text);
  });
});
