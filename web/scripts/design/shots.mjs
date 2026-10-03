// make design-shots STATES="chat-*" [ROUND=v0.3] [THEME=light|dark|both]: render states to PNG (design spec §5).
import { mkdirSync, mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { isMain, run } from './lib/cli.mjs';
import { matchStates } from './lib/diff.mjs';
import { exportDir, repoRoot, requireTag } from './lib/git.mjs';
import { PROTOTYPE, SHOTS } from './lib/paths.mjs';
import { readRawStates, shootState, withBrowser } from './lib/prototype.mjs';

const THEMES = { light: ['light'], dark: ['dark'], both: ['light', 'dark'] };

async function main() {
  const { values } = parseArgs({
    options: { states: { type: 'string' }, round: { type: 'string' }, theme: { type: 'string', default: 'light' } },
  });
  const themes = THEMES[values.theme];
  if (!themes) throw new Error(`THEME must be light, dark or both, got "${values.theme}"`);
  if (!values.states?.trim()) throw new Error('STATES is required, e.g. STATES="chat-*,library-empty"');

  const root = repoRoot();
  const label = values.round || 'working';
  let protoDir = join(root, PROTOTYPE);
  let tmp;
  if (values.round) {
    const tag = requireTag(values.round, root);
    tmp = mkdtempSync(join(tmpdir(), 'design-shots-'));
    exportDir(tag, PROTOTYPE, tmp, root);
    protoDir = tmp;
  }
  try {
    const index = join(protoDir, 'index.html');
    const outDir = join(root, SHOTS, label);
    const count = await withBrowser(async (browser) => {
      const ids = (await readRawStates(browser, index)).map((s) => s.id);
      const { matched, unmatched } = matchStates(ids, values.states);
      if (unmatched.length) {
        throw new Error(`No state matches ${unmatched.join(', ')} in ${label}. State ids are listed in sdd/design/states.json`);
      }
      mkdirSync(outDir, { recursive: true });
      for (const id of matched) {
        for (const theme of themes) await shootState(browser, index, id, theme, join(outDir, `${id}.${theme}.png`));
      }
      return matched.length * themes.length;
    });
    console.log(`Wrote ${count} screenshots to ${SHOTS}/${label}/`);
  } finally {
    if (tmp) rmSync(tmp, { recursive: true, force: true });
  }
}

if (isMain(import.meta.url)) run(main);
