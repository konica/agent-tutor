// make design-diff FROM=v0.2 [TO=v0.3]: state ids that changed between rounds, and open issues that cite them (design spec §5, §8 step 5).
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { isMain, run } from './lib/cli.mjs';
import { diffStates, mentions } from './lib/diff.mjs';
import { repoRoot, requireTag, showFile } from './lib/git.mjs';
import { STATES_JSON } from './lib/paths.mjs';

function statesAt(root, round) {
  if (!round) return JSON.parse(readFileSync(join(root, STATES_JSON), 'utf8'));
  const tag = requireTag(round, root);
  try {
    return JSON.parse(showFile(tag, STATES_JSON, root));
  } catch {
    throw new Error(`${tag} has no ${STATES_JSON}; was it accepted with make design-accept?`);
  }
}

function openIssues(root) {
  try {
    const out = execFileSync('gh', ['issue', 'list', '--state', 'open', '--limit', '500', '--json', 'number,title,body,url'], {
      cwd: root,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    return JSON.parse(out);
  } catch {
    return null;
  }
}

async function main() {
  const { values } = parseArgs({ options: { from: { type: 'string' }, to: { type: 'string' } } });
  if (!values.from) throw new Error('FROM is required, e.g. FROM=v0.2');
  const root = repoRoot();
  const d = diffStates(statesAt(root, values.from), statesAt(root, values.to));
  console.log(`States from ${values.from} to ${values.to || 'working copy'}:`);
  for (const [name, ids] of Object.entries(d)) console.log(`  ${name} (${ids.length}): ${ids.join(', ') || '—'}`);

  const stale = [...d.removed, ...d.changed];
  if (!stale.length) return;
  const issues = openIssues(root);
  if (!issues) {
    console.warn('gh is not available or not signed in; skipped the issue search.');
    return;
  }
  const hits = issues
    .map((i) => ({ ...i, ids: stale.filter((id) => mentions(`${i.title}\n${i.body}`, id)) }))
    .filter((i) => i.ids.length);
  console.log(`Open issues citing removed or changed states (${hits.length}):`);
  for (const i of hits) console.log(`  #${i.number} ${i.title} — ${i.ids.join(', ')}`);
}

if (isMain(import.meta.url)) run(main);
