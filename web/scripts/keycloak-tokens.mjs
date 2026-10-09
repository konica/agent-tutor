// Copies the design tokens into the Keycloak login theme (#48), so Keycloak's pages use the app's colors and fonts.
// The web app switches themes with [data-theme="dark"]; keycloak.v2 puts .pf-v5-theme-dark on <html> instead.
// Usage: node scripts/keycloak-tokens.mjs [--check]   (--check fails when the theme's copy is stale)
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const source = fileURLToPath(new URL("../src/styles/tokens.css", import.meta.url));
const target = fileURLToPath(
  new URL("../../local/keycloak/themes/smart-tutor/login/resources/css/tokens.css", import.meta.url),
);

// Compare with LF line endings: Windows checkouts (text=auto) turn both files into CRLF.
const lf = (text) => text.replaceAll("\r\n", "\n");
const tokens = lf(readFileSync(source, "utf8"));
if (!tokens.includes('[data-theme="dark"]')) throw new Error(`${source} has no [data-theme="dark"] block`);
const generated =
  "/* Generated from web/src/styles/tokens.css by `npm run keycloak:tokens` (web/). Do not edit. */\n" +
  tokens.replaceAll('[data-theme="dark"]', ".pf-v5-theme-dark");

if (process.argv.includes("--check")) {
  let current = "";
  try {
    current = lf(readFileSync(target, "utf8"));
  } catch {}
  if (current !== generated) {
    console.error(`${target} is stale: run \`npm run keycloak:tokens\` in web/`);
    process.exit(1);
  }
} else {
  writeFileSync(target, generated);
}
