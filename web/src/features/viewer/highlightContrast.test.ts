// The highlight is drawn over the white PDF page in both themes, so its colors are fixed; this keeps them readable.
import { describe, expect, it } from "vitest";

import tokens from "../../styles/tokens.css?raw";

type Rgba = { r: number; g: number; b: number; a: number };

function token(name: string): Rgba {
  const value = new RegExp(`${name}:\\s*([^;]+);`).exec(tokens)?.[1]?.trim();
  if (!value) throw new Error(`${name} is not in tokens.css`);
  return parse(value);
}

function parse(value: string): Rgba {
  const hex = /^#([0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const n = parseInt(hex[1]!, 16);
    return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255, a: 1 };
  }
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(value);
  if (rgba) return { r: Number(rgba[1]), g: Number(rgba[2]), b: Number(rgba[3]), a: rgba[4] === undefined ? 1 : Number(rgba[4]) };
  throw new Error(`can't parse ${value}`);
}

const WHITE: Rgba = { r: 255, g: 255, b: 255, a: 1 };

function over(top: Rgba, bottom: Rgba): Rgba {
  const mix = (t: number, b: number) => t * top.a + b * (1 - top.a);
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a: 1 };
}

function luminance({ r, g, b }: Rgba): number {
  const channel = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: Rgba, b: Rgba): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe("citation highlight colors", () => {
  const fill = over(token("--cite-fill"), WHITE);

  it("keeps black and dark-grey PDF text readable under the fill", () => {
    expect(contrast(parse("#000000"), fill)).toBeGreaterThanOrEqual(4.5);
    expect(contrast(parse("#595959"), fill)).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps the label readable on the marker color", () => {
    expect(contrast(token("--cite-on-mark"), token("--cite-mark"))).toBeGreaterThanOrEqual(4.5);
  });

  it("defines the colors once, outside the dark theme", () => {
    const dark = tokens.slice(tokens.indexOf('[data-theme="dark"]'));
    expect(dark).not.toMatch(/--cite-/);
  });
});
