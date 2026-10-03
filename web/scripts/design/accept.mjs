// make design-accept ROUND=v0.3: record an accepted round in rounds.md and states.json (design spec §5, §8 step 4).
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { parseArgs } from 'node:util';
import { isMain, run } from './lib/cli.mjs';
import { git, repoRoot, roundTag, tagExists } from './lib/git.mjs';
import { BRIEF, PRD, ROUNDS_MD, STATES_JSON } from './lib/paths.mjs';
import { addRoundRow, checkRound, readBriefPrdVersion, readBriefVersion, readPrdVersion } from './lib/rounds.mjs';
import { serializeStates } from './lib/states.mjs';
import { buildStates } from './states.mjs';

async function main() {
  const { values } = parseArgs({
    options: { round: { type: 'string' }, feedback: { type: 'string' }, by: { type: 'string' } },
  });
  const root = repoRoot();
  const brief = readFileSync(join(root, BRIEF), 'utf8');
  const round = values.round ?? '';
  const briefVersion = readBriefVersion(brief);
  checkRound(round, briefVersion, tagExists(roundTag(round), root));

  const states = await buildStates(root);
  const roundsFile = join(root, ROUNDS_MD);
  const briefPrd = readBriefPrdVersion(brief);
  const by = values.by || git(['config', 'user.name'], { cwd: root }).trim();
  const rounds = addRoundRow(existsSync(roundsFile) ? readFileSync(roundsFile, 'utf8') : null, {
    round,
    brief: briefVersion,
    prd: briefPrd,
    states: states.length,
    accepted: `${new Date().toISOString().slice(0, 10)}, ${by}`,
    feedback: values.feedback || '—',
  });

  writeFileSync(join(root, STATES_JSON), serializeStates(states));
  writeFileSync(roundsFile, rounds);
  console.log(`Recorded round ${round}: ${states.length} states, brief ${briefVersion}, PRD ${briefPrd}.`);

  const prdNow = readPrdVersion(readFileSync(join(root, PRD), 'utf8'));
  if (prdNow !== briefPrd) {
    console.warn(
      `Warning: brief ${briefVersion} is based on PRD ${briefPrd}, but ${PRD} is ${prdNow}. ` +
        'Before merging, check that the PRD changes since then do not change what users see (design spec §9).',
    );
  }
  console.log(
    `Next: commit ${ROUNDS_MD}, ${STATES_JSON} and the prototype, open a PR, and after it merges run:\n` +
      `  git tag ${roundTag(round)} <merge commit> && git push origin ${roundTag(round)}`,
  );
}

if (isMain(import.meta.url)) run(main);
