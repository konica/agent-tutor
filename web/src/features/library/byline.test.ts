import { describe, expect, it } from "vitest";

import { byline } from "./byline";

describe("byline", () => {
  it("shows one author in full", () => expect(byline(["Patrick Lewis"], 2020)).toBe("Patrick Lewis · 2020"));
  it("joins two last names with and", () => expect(byline(["Ashish Vaswani", "Noam Shazeer"], 2017)).toBe("Vaswani and Shazeer · 2017"));
  it("abbreviates three or more with et al.", () => expect(byline(["Timo Schick", "Jane Dwivedi-Yu", "Roberto Dessì"], 2023)).toBe("Schick et al. · 2023"));
  it("shows the year alone without authors", () => expect(byline([], 2023)).toBe("2023"));
  it("shows the authors alone without a year", () => expect(byline(["Patrick Lewis"], null)).toBe("Patrick Lewis"));
  it("is empty when both are missing", () => expect(byline([], null)).toBe(""));
  it("takes the last whitespace-separated token as the last name", () => expect(byline(["A.  B.  Smith ", "C. Jones"], null)).toBe("Smith and Jones"));
});
