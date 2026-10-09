// The web app has no @types/node; contrast.test.ts only needs readFileSync to read tokens.css.
declare module "node:fs" {
  export function readFileSync(path: URL, encoding: "utf8"): string;
}
