// make design-states: write sdd/design/states.json from the prototype's window.ST.STATES (design spec §5).
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { isMain, run } from './lib/cli.mjs';
import { repoRoot } from './lib/git.mjs';
import { PRD, PROTOTYPE, STATES_JSON } from './lib/paths.mjs';
import { readRawStates, withBrowser } from './lib/prototype.mjs';
import { isCurrent, normalizeStates, serializeStates } from './lib/states.mjs';
import { storyIdsFromPrd } from './lib/stories.mjs';

export async function buildStates(root, protoDir = join(root, PROTOTYPE)) {
  const known = storyIdsFromPrd(readFileSync(join(root, PRD), 'utf8'));
  const raw = await withBrowser((b) => readRawStates(b, join(protoDir, 'index.html')));
  return normalizeStates(raw, known);
}

async function main() {
  const { values } = parseArgs({ options: { check: { type: 'boolean', default: false } } });
  const root = repoRoot();
  const states = await buildStates(root);
  const next = serializeStates(states);
  const file = join(root, STATES_JSON);
  if (values.check) {
    if (!isCurrent(existsSync(file) ? readFileSync(file, 'utf8') : null, next)) {
      throw new Error(`${STATES_JSON} is out of date with the prototype. Run: make design-states`);
    }
    console.log(`${STATES_JSON} is current (${states.length} states)`);
    return;
  }
  writeFileSync(file, next);
  console.log(`Wrote ${STATES_JSON}: ${states.length} states`);
}

if (isMain(import.meta.url)) run(main);
