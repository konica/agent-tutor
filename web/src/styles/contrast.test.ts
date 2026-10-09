// @vitest-environment node
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const css = readFileSync(new URL("./tokens.css", import.meta.url), "utf8");

const block = (selector: string) => {
  const start = css.indexOf(selector);
  const body = css.slice(css.indexOf("{", start) + 1, css.indexOf("}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+):\s*([^;]+);/g)].map((m) => [m[1], m[2]!.trim()]));
};
const light = block(':root, [data-theme="light"]');
const dark = { ...light, ...block('[data-theme="dark"]') };

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!;
}
const ratio = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi! + 0.05) / (lo! + 0.05);
};

describe("tokens", () => {
  it.each([["light", light], ["dark", dark]] as const)("%s theme keeps 4.5:1 for secondary text and placeholders", (_, theme) => {
    for (const fg of ["--text-2", "--text-3"]) for (const bg of ["--bg", "--surface", "--surface-2"]) expect(ratio(theme[fg]!, theme[bg]!), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
  });

  it("defines the compact tokens", () => {
    for (const name of ["--fs-13", "--lh-read", "--sp-0", "--r-lg", "--nav-w-collapsed", "--viewer-w"]) expect(light[name], name).toBeDefined();
    expect(light["--fs-40"]).toBeUndefined();
  });
});
