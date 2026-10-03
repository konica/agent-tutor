// Accepted design rounds: version checks and the sdd/design/rounds.md table (design spec §4.1).

const HEADER = [
  '# Accepted design rounds',
  '',
  'One row per accepted round, newest first. Each round is a git tag. Written by `make design-accept`; see `sdd/specs/2026-10-03-design-to-code-loop-design.md` §4.1.',
  '',
  '| Round | Tag | Brief | PRD | States | Accepted | Open feedback |',
  '|---|---|---|---|---|---|---|',
  '',
];

function headerValue(text, label, pattern) {
  const line = text.split(/\r?\n/).find((l) => l.includes(`**${label}**`));
  const match = line?.match(pattern);
  if (!match) throw new Error(`Could not read "${label}" from the document header`);
  return match[1];
}

export const readBriefVersion = (brief) => headerValue(brief, 'Brief version', /\b(v\d+\.\d+)\b/);
export const readBriefPrdVersion = (brief) => headerValue(brief, 'Based on', /\b(v\d+\.\d+)\b/);
export const readPrdVersion = (prd) => headerValue(prd, 'Status', /\b(v\d+\.\d+)\b/);

export function checkRound(round, briefVersion, tagExists) {
  if (!/^v\d+\.\d+$/.test(round)) throw new Error(`ROUND must look like v0.3, got "${round}"`);
  if (round !== briefVersion) {
    throw new Error(`Round ${round} must match the brief version (${briefVersion}): a round is named after the brief it answers`);
  }
  if (tagExists) throw new Error(`Tag design-${round} already exists: round ${round} was accepted before`);
}

const formatRow = (r) =>
  `| ${r.round} | \`design-${r.round}\` | ${r.brief} | ${r.prd} | ${r.states} | ${r.accepted} | ${r.feedback} |`;

export function addRoundRow(roundsMd, row) {
  const lines = (roundsMd ?? HEADER.join('\n')).split(/\r?\n/);
  if (lines.some((l) => l.startsWith(`| ${row.round} |`))) throw new Error(`Round ${row.round} is already in rounds.md`);
  const separator = lines.findIndex((l) => /^\|(-+\|)+$/.test(l.trim()));
  if (separator < 0) throw new Error('rounds.md has no table');
  lines.splice(separator + 1, 0, formatRow(row));
  return lines.join('\n');
}
