# Design tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `make design-states`, `design-accept`, `design-shots` and `design-diff` commands, the generated `sdd/design/states.json`, a CI check, and the "Design inputs" agent instructions (rollout item 3 of the design-to-code loop).

**Architecture:** Plain Node ES modules in `web/scripts/design/`. Pure logic (story parsing, state validation, rounds table, diffing, pattern matching) lives in `lib/` and is unit-tested with `node:test`. Two thin adapters touch the outside world: `lib/prototype.mjs` (headless Chromium through Playwright) and `lib/git.mjs` (tags and files at a tag). Four command files wire them together; `Makefile` targets call them through `npm run`.

**Tech Stack:** Node 22+, `node:test`, `node:util` `parseArgs`, Playwright 1.63 (`playwright` package, Chromium only), git, optional `gh`.

**Spec:** `sdd/specs/2026-10-03-design-to-code-loop-design.md` (§4–§7).

## Global Constraints

- Prototype folder: `sdd/design/prototype/`; entry `index.html`; state index `window.ST.STATES` (spec §5.1).
- State URL: `index.html?shot=1#/<state-id>` (spec §5.1).
- `sdd/design/states.json` stores bare ids; entries `{ id, group, ref, desc, release, stories }` (spec §4.2).
- Accepted round = git tag `design-v0.x`, logged in `sdd/design/rounds.md` with columns `Round | Tag | Brief | PRD | States | Accepted | Open feedback` (spec §4.1).
- Screenshots: 1440×900, `.design-shots/<round or working>/<id>.<theme>.png`, git-ignored (spec §5).
- No script talks to the Open Design app, daemon, or MCP server (spec §5).
- `sdd/design/prototype/**` is `-text` in `.gitattributes`; other generated files may be checked out with CRLF on Windows.
- Docs in plain, short sentences; cite spec sections.

## Review Focus

- **Windows checkout with `core.autocrlf=true`:** `states.json` and `rounds.md` arrive with CRLF; `--check` must still report "current", and the rounds table must still parse. Tests: `isCurrent` (Task 1), CRLF `addRoundRow` (Task 2).
- **Round name that doesn't match the brief, or is malformed, or is already tagged:** `design-accept` refuses before writing anything. Tests: `checkRound` (Task 2).
- **Round already in `rounds.md`:** refused, file unchanged. Test: `addRoundRow` duplicate (Task 2).
- **`STATES` pattern that matches nothing** (typo such as `chta-*`): fail and name the pattern, instead of silently rendering nothing. Test: `matchStates` (Task 3).
- **Tag missing locally** (round not accepted, or tags not fetched): clear message naming the tag and the fix. Test: `requireTag` (Task 4).

---

### Task 1: State index logic

**Files:**
- Create: `web/scripts/design/lib/stories.mjs`
- Create: `web/scripts/design/lib/states.mjs`
- Create: `web/scripts/design/test/states.test.mjs`
- Modify: `web/package.json` (scripts)

**Interfaces:**
- Produces: `parseStories(ref: string, knownIds?: string[]): string[]`, `storyIdsFromPrd(prdText: string): string[]`, `normalizeStates(raw: unknown, knownIds: string[]): State[]`, `serializeStates(states: State[]): string`, `isCurrent(current: string | null, next: string): boolean`. `State = { id, group, ref, desc, release, stories }`.

- [ ] **Step 1: Write the failing tests** — `web/scripts/design/test/states.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseStories, storyIdsFromPrd } from '../lib/stories.mjs';
import { normalizeStates, serializeStates, isCurrent } from '../lib/states.mjs';

const KNOWN = ['US-1', 'US-2', 'US-2b', 'US-3', 'US-3b', 'US-4', 'US-9', 'US-10', 'US-10b', 'US-11', 'US-14', 'US-15', 'US-16'];

test('parseStories reads single ids, lists and b variants', () => {
  assert.deepEqual(parseStories('§6.3 · US-2, US-10, US-11', KNOWN), ['US-2', 'US-10', 'US-11']);
  assert.deepEqual(parseStories('§6.4 · US-2b', KNOWN), ['US-2b']);
  assert.deepEqual(parseStories('§10–11', KNOWN), []);
});

test('parseStories expands en-dash ranges using known ids, b variants included', () => {
  assert.deepEqual(parseStories('§6.6 · US-3–10', KNOWN), ['US-3', 'US-3b', 'US-4', 'US-9', 'US-10', 'US-10b']);
  assert.deepEqual(parseStories('§8 · US-14-16', KNOWN), ['US-14', 'US-15', 'US-16']);
});

test('parseStories falls back to plain numbers without known ids', () => {
  assert.deepEqual(parseStories('US-14–16'), ['US-14', 'US-15', 'US-16']);
});

test('storyIdsFromPrd returns unique ids in story order', () => {
  assert.deepEqual(storyIdsFromPrd('US-10 then US-2b, US-2, US-10b and US-2 again'), ['US-2', 'US-2b', 'US-10', 'US-10b']);
});

test('normalizeStates keeps prototype order and derives stories and release', () => {
  const raw = [
    { id: 'chat-new', group: 'Chat', ref: '§6.6 · US-3–4', desc: 'New chat.', view: 'fn' },
    { id: 'r2-map', group: 'R2', ref: '§7 · US-19', desc: 'Map.', release: 2 },
  ];
  assert.deepEqual(normalizeStates(raw, KNOWN), [
    { id: 'chat-new', group: 'Chat', ref: '§6.6 · US-3–4', desc: 'New chat.', release: 1, stories: ['US-3', 'US-3b', 'US-4'] },
    { id: 'r2-map', group: 'R2', ref: '§7 · US-19', desc: 'Map.', release: 2, stories: ['US-19'] },
  ]);
});

test('normalizeStates rejects a missing index, bad ids and duplicates', () => {
  assert.throws(() => normalizeStates(null, KNOWN), /missing or empty/);
  assert.throws(() => normalizeStates([], KNOWN), /missing or empty/);
  assert.throws(() => normalizeStates([{ id: 'Chat New' }], KNOWN), /invalid id/);
  assert.throws(() => normalizeStates([{ id: 'a' }, { id: 'a' }], KNOWN), /Duplicate state id: a/);
});

test('serializeStates is stable JSON with a trailing newline', () => {
  assert.equal(serializeStates([{ id: 'a' }]), '[\n  {\n    "id": "a"\n  }\n]\n');
});

test('isCurrent ignores CRLF from a Windows checkout', () => {
  assert.equal(isCurrent('[\r\n  1\r\n]\r\n', '[\n  1\n]\n'), true);
  assert.equal(isCurrent('[\n  2\n]\n', '[\n  1\n]\n'), false);
  assert.equal(isCurrent(null, '[]\n'), false);
});
```

Add to `web/package.json` scripts: `"test:design": "node --test \"scripts/design/test/*.test.mjs\""`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npm run test:design`
Expected: FAIL, `Cannot find module '../lib/stories.mjs'`.

- [ ] **Step 3: Implement** — `web/scripts/design/lib/stories.mjs`:

```js
// Story ids (PRD §8) named by a prototype state's `ref`, e.g. "§6.6 · US-3–10".

const STORY = /US-(\d+)(b?)(?:\s*[–-]\s*(\d+))?/g;

const storyNumber = (id) => Number(id.slice(3).replace(/b$/, ''));

const byStory = (a, b) => storyNumber(a) - storyNumber(b) || a.localeCompare(b);

export function parseStories(ref, knownIds = []) {
  const out = [];
  const add = (id) => {
    if (!out.includes(id)) out.push(id);
  };
  for (const [, from, suffix, to] of ref.matchAll(STORY)) {
    if (!to) {
      add(`US-${from}${suffix}`);
      continue;
    }
    const lo = Number(from);
    const hi = Number(to);
    const known = knownIds.filter((id) => storyNumber(id) >= lo && storyNumber(id) <= hi).sort(byStory);
    if (known.length) known.forEach(add);
    else for (let n = lo; n <= hi; n++) add(`US-${n}`);
  }
  return out;
}

export function storyIdsFromPrd(prdText) {
  return [...new Set(prdText.match(/US-\d+b?/g) ?? [])].sort(byStory);
}
```

`web/scripts/design/lib/states.mjs`:

```js
// The state index of the prototype, written to sdd/design/states.json (design spec §4.2).
import { parseStories } from './stories.mjs';

const ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;

export function normalizeStates(raw, knownIds) {
  if (!Array.isArray(raw) || raw.length === 0) throw new Error('window.ST.STATES is missing or empty');
  const seen = new Set();
  return raw.map((s, i) => {
    if (typeof s?.id !== 'string' || !ID.test(s.id)) throw new Error(`State ${i} has an invalid id: ${JSON.stringify(s?.id)}`);
    if (seen.has(s.id)) throw new Error(`Duplicate state id: ${s.id}`);
    seen.add(s.id);
    const ref = typeof s.ref === 'string' ? s.ref : '';
    return {
      id: s.id,
      group: String(s.group ?? ''),
      ref,
      desc: String(s.desc ?? ''),
      release: Number(s.release) || 1,
      stories: parseStories(ref, knownIds),
    };
  });
}

export const serializeStates = (states) => `${JSON.stringify(states, null, 2)}\n`;

export const isCurrent = (current, next) => current !== null && current.replace(/\r\n/g, '\n') === next;
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npm run test:design`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add web/scripts/design web/package.json
git commit -m "Add state index logic for the design tooling"
```

### Task 2: Versions, round checks and the rounds table

**Files:**
- Create: `web/scripts/design/lib/rounds.mjs`
- Create: `web/scripts/design/test/rounds.test.mjs`

**Interfaces:**
- Produces: `readBriefVersion(brief): string`, `readBriefPrdVersion(brief): string`, `readPrdVersion(prd): string`, `checkRound(round, briefVersion, tagExists: boolean): void` (throws), `addRoundRow(roundsMd: string | null, row: Row): string`. `Row = { round, brief, prd, states: number, accepted, feedback }`.

- [ ] **Step 1: Write the failing tests** — `web/scripts/design/test/rounds.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readBriefVersion, readBriefPrdVersion, readPrdVersion, checkRound, addRoundRow } from '../lib/rounds.mjs';

const BRIEF = '| **Brief version** | v0.3 |\n| **Based on** | `sdd/prd.md` Draft v2.1 |\n';
const PRD = '| **Status** | Draft v2.3 (learners upload their own documents) |\n';
const ROW = { round: 'v0.3', brief: 'v0.3', prd: 'v2.1', states: 101, accepted: '2026-10-04, Thao Dinh', feedback: 'Q7, D1–D12' };

test('reads versions from the brief and PRD headers', () => {
  assert.equal(readBriefVersion(BRIEF), 'v0.3');
  assert.equal(readBriefPrdVersion(BRIEF), 'v2.1');
  assert.equal(readPrdVersion(PRD), 'v2.3');
  assert.throws(() => readBriefVersion('no header'), /Brief version/);
});

test('checkRound accepts a round named after the brief version', () => {
  assert.doesNotThrow(() => checkRound('v0.3', 'v0.3', false));
});

test('checkRound refuses a malformed, mismatched or already tagged round', () => {
  assert.throws(() => checkRound('0.3', 'v0.3', false), /like v0\.3/);
  assert.throws(() => checkRound('v0.4', 'v0.3', false), /must match the brief version \(v0\.3\)/);
  assert.throws(() => checkRound('v0.3', 'v0.3', true), /design-v0\.3 already exists/);
});

test('addRoundRow creates the file with a header when missing', () => {
  const md = addRoundRow(null, ROW);
  assert.match(md, /^# Accepted design rounds/);
  assert.match(md, /\| v0\.3 \| `design-v0\.3` \| v0\.3 \| v2\.1 \| 101 \| 2026-10-04, Thao Dinh \| Q7, D1–D12 \|/);
  assert.ok(md.endsWith('\n'));
});

test('addRoundRow puts the newest round first', () => {
  const md = addRoundRow(addRoundRow(null, ROW), { ...ROW, round: 'v0.4', brief: 'v0.4' });
  assert.ok(md.indexOf('| v0.4 |') < md.indexOf('| v0.3 |'));
});

test('addRoundRow parses a CRLF file and refuses a duplicate round', () => {
  const crlf = addRoundRow(null, ROW).replace(/\n/g, '\r\n');
  assert.throws(() => addRoundRow(crlf, ROW), /v0\.3 is already in rounds\.md/);
  assert.match(addRoundRow(crlf, { ...ROW, round: 'v0.4' }), /\| v0\.4 \|/);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npm run test:design`
Expected: FAIL, `Cannot find module '../lib/rounds.mjs'`.

- [ ] **Step 3: Implement** — `web/scripts/design/lib/rounds.mjs`:

```js
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npm run test:design`
Expected: PASS, 14 tests.

- [ ] **Step 5: Commit**

```bash
git add web/scripts/design
git commit -m "Add round checks and the rounds table for the design tooling"
```

### Task 3: Diffing and state patterns

**Files:**
- Create: `web/scripts/design/lib/diff.mjs`
- Create: `web/scripts/design/test/diff.test.mjs`

**Interfaces:**
- Produces: `diffStates(before: State[], after: State[]): { added: string[], removed: string[], changed: string[] }`, `mentions(text: string, id: string): boolean`, `matchStates(ids: string[], patterns: string): { matched: string[], unmatched: string[] }`.

- [ ] **Step 1: Write the failing tests** — `web/scripts/design/test/diff.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { diffStates, mentions, matchStates } from '../lib/diff.mjs';

const s = (id, desc = 'd', ref = 'r') => ({ id, desc, ref });

test('diffStates lists added, removed and changed ids', () => {
  const before = [s('a'), s('b'), s('c'), s('d')];
  const after = [s('a'), s('b', 'new desc'), s('c', 'd', 'new ref'), s('e')];
  assert.deepEqual(diffStates(before, after), { added: ['e'], removed: ['d'], changed: ['b', 'c'] });
});

test('mentions matches whole state ids only', () => {
  assert.equal(mentions('States: `chat-new@v0.3`, x', 'chat-new'), true);
  assert.equal(mentions('chat-new', 'chat-new'), true);
  assert.equal(mentions('`chat-new-conversation@v0.3`', 'chat-new'), false);
  assert.equal(mentions('old-chat-new@v0.3', 'chat-new'), false);
});

test('matchStates supports exact ids, * globs, commas and spaces', () => {
  const ids = ['chat-new', 'chat-error', 'library-empty', 'components'];
  assert.deepEqual(matchStates(ids, 'chat-*, components'), { matched: ['chat-new', 'chat-error', 'components'], unmatched: [] });
});

test('matchStates reports patterns that match nothing', () => {
  assert.deepEqual(matchStates(['chat-new'], 'chta-* chat-new'), { matched: ['chat-new'], unmatched: ['chta-*'] });
  assert.deepEqual(matchStates(['chat-new'], ' '), { matched: [], unmatched: [] });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npm run test:design`
Expected: FAIL, `Cannot find module '../lib/diff.mjs'`.

- [ ] **Step 3: Implement** — `web/scripts/design/lib/diff.mjs`:

```js
// Compare state indexes between rounds and select states by pattern (design spec §5).

export function diffStates(before, after) {
  const old = new Map(before.map((s) => [s.id, s]));
  const ids = new Set(after.map((s) => s.id));
  return {
    added: after.filter((s) => !old.has(s.id)).map((s) => s.id),
    removed: before.filter((s) => !ids.has(s.id)).map((s) => s.id),
    changed: after
      .filter((s) => old.has(s.id) && (old.get(s.id).desc !== s.desc || old.get(s.id).ref !== s.ref))
      .map((s) => s.id),
  };
}

// State ids are [a-z0-9-], so a mention must not continue with one of those characters.
export const mentions = (text, id) => new RegExp(`(^|[^a-z0-9-])${id}(?![a-z0-9-])`).test(text);

export function matchStates(ids, patterns) {
  const matched = [];
  const unmatched = [];
  for (const pattern of patterns.split(/[\s,]+/).filter(Boolean)) {
    const re = new RegExp(`^${pattern.replace(/[.+?^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*')}$`);
    const hits = ids.filter((id) => re.test(id));
    if (!hits.length) unmatched.push(pattern);
    for (const id of hits) if (!matched.includes(id)) matched.push(id);
  }
  return { matched, unmatched };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd web && npm run test:design`
Expected: PASS, 18 tests.

- [ ] **Step 5: Commit**

```bash
git add web/scripts/design
git commit -m "Add state diffing and pattern matching for the design tooling"
```

### Task 4: Git and browser adapters

**Files:**
- Create: `web/scripts/design/lib/git.mjs`
- Create: `web/scripts/design/lib/prototype.mjs`
- Create: `web/scripts/design/test/git.test.mjs`
- Create: `web/scripts/design/test/prototype.test.mjs`
- Create: `web/scripts/design/test/fixtures/proto/index.html`
- Create: `web/scripts/design/test/fixtures/broken/index.html`
- Modify: `web/package.json` (devDependency `playwright`)

**Interfaces:**
- Produces: `git(args, opts?)`, `repoRoot(cwd?)`, `roundTag(round)`, `tagExists(tag, cwd?)`, `requireTag(round, cwd?)`, `showFile(ref, path, cwd?)`, `exportDir(ref, dir, dest, cwd?)`; `VIEWPORT`, `withBrowser(fn)`, `readRawStates(browser, indexHtml)`, `shootState(browser, indexHtml, id, theme, outFile)`.

- [ ] **Step 1: Add Playwright and install Chromium**

Run: `cd web && npm install --save-dev playwright@1.63.0 && npx playwright install chromium`

- [ ] **Step 2: Write the fixtures and failing tests**

`web/scripts/design/test/fixtures/proto/index.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Fixture</title></head>
<body>
  <header class="review-bar">Review bar</header>
  <main id="root"></main>
  <script>
    window.ST = { STATES: [
      { id: 'home-empty', group: 'Home', ref: '§6.3 · US-2', desc: 'Empty home.', view: function () {} },
      { id: 'r2-map', group: 'R2', ref: '§7 · US-19', desc: 'Map.', release: 2 }
    ] };
    const show = () => { document.getElementById('root').textContent = 'State ' + location.hash.slice(2); };
    window.addEventListener('hashchange', show);
    show();
  </script>
</body>
</html>
```

`web/scripts/design/test/fixtures/broken/index.html`:

```html
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Broken</title></head>
<body><script>throw new Error('prototype failed to load');</script></body>
</html>
```

`web/scripts/design/test/prototype.test.mjs`:

```js
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { withBrowser, readRawStates, shootState } from '../lib/prototype.mjs';

const fixtures = join(dirname(fileURLToPath(import.meta.url)), 'fixtures');

test('readRawStates returns plain state fields from window.ST.STATES', async () => {
  const raw = await withBrowser((b) => readRawStates(b, join(fixtures, 'proto', 'index.html')));
  assert.deepEqual(raw, [
    { id: 'home-empty', group: 'Home', ref: '§6.3 · US-2', desc: 'Empty home.', release: null },
    { id: 'r2-map', group: 'R2', ref: '§7 · US-19', desc: 'Map.', release: 2 },
  ]);
});

test('readRawStates reports page errors when the index never appears', async () => {
  await assert.rejects(
    withBrowser((b) => readRawStates(b, join(fixtures, 'broken', 'index.html'), 1000)),
    /window\.ST\.STATES never appeared.*prototype failed to load/,
  );
});

test('shootState writes a PNG of the state', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'shots-'));
  try {
    const out = join(dir, 'home-empty.dark.png');
    await withBrowser((b) => shootState(b, join(fixtures, 'proto', 'index.html'), 'home-empty', 'dark', out));
    assert.deepEqual([...readFileSync(out).subarray(0, 4)], [0x89, 0x50, 0x4e, 0x47]);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
```

`web/scripts/design/test/git.test.mjs`:

```js
import { test, before, after } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { git, tagExists, requireTag, showFile, exportDir } from '../lib/git.mjs';

let repo;

before(() => {
  repo = mkdtempSync(join(tmpdir(), 'design-git-'));
  const run = (...args) => git(args, { cwd: repo });
  run('init', '-q');
  run('config', 'user.email', 'test@example.com');
  run('config', 'user.name', 'Test');
  mkdirSync(join(repo, 'sdd/design/prototype/js'), { recursive: true });
  writeFileSync(join(repo, 'sdd/design/prototype/index.html'), '<p>v0.3</p>\r\n');
  writeFileSync(join(repo, 'sdd/design/prototype/js/a.js'), 'a');
  writeFileSync(join(repo, 'sdd/design/states.json'), '[]\n');
  run('add', '.');
  run('-c', 'core.autocrlf=false', 'commit', '-qm', 'round');
  run('tag', 'design-v0.3');
});

after(() => rmSync(repo, { recursive: true, force: true }));

test('tagExists and requireTag find accepted rounds', () => {
  assert.equal(tagExists('design-v0.3', repo), true);
  assert.equal(requireTag('v0.3', repo), 'design-v0.3');
});

test('requireTag explains how to fix a missing tag', () => {
  assert.equal(tagExists('design-v0.9', repo), false);
  assert.throws(() => requireTag('v0.9', repo), /Tag design-v0\.9 not found.*make design-accept.*git fetch --tags/);
});

test('showFile reads a file at a tag', () => {
  assert.equal(showFile('design-v0.3', 'sdd/design/states.json', repo), '[]\n');
});

test('exportDir writes the folder at a tag byte for byte', () => {
  const dest = mkdtempSync(join(tmpdir(), 'design-export-'));
  try {
    assert.equal(exportDir('design-v0.3', 'sdd/design/prototype', dest, repo), 2);
    assert.equal(readFileSync(join(dest, 'index.html'), 'utf8'), '<p>v0.3</p>\r\n');
    assert.equal(readFileSync(join(dest, 'js', 'a.js'), 'utf8'), 'a');
  } finally {
    rmSync(dest, { recursive: true, force: true });
  }
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd web && npm run test:design`
Expected: FAIL, `Cannot find module '../lib/prototype.mjs'` and `'../lib/git.mjs'`.

- [ ] **Step 4: Implement** — `web/scripts/design/lib/git.mjs`:

```js
// Git access for the design tooling: accepted rounds are tags (design spec §3, §4).
import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';

export const git = (args, { cwd, encoding = 'utf8' } = {}) =>
  execFileSync('git', args, { cwd, encoding, maxBuffer: 64 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'] });

export const repoRoot = (cwd) => git(['rev-parse', '--show-toplevel'], { cwd }).trim();

export const roundTag = (round) => `design-${round}`;

export function tagExists(tag, cwd) {
  try {
    git(['rev-parse', '--verify', '--quiet', `refs/tags/${tag}`], { cwd });
    return true;
  } catch {
    return false;
  }
}

export function requireTag(round, cwd) {
  const tag = roundTag(round);
  if (!tagExists(tag, cwd)) {
    throw new Error(`Tag ${tag} not found. Accept round ${round} first (make design-accept), or run: git fetch --tags`);
  }
  return tag;
}

export const showFile = (ref, path, cwd) => git(['show', `${ref}:${path}`], { cwd });

export function exportDir(ref, dir, dest, cwd) {
  const files = git(['ls-tree', '-r', '--name-only', ref, '--', dir], { cwd }).split('\n').filter(Boolean);
  for (const file of files) {
    const out = join(dest, relative(dir, file));
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, git(['show', `${ref}:${file}`], { cwd, encoding: 'buffer' }));
  }
  return files.length;
}
```

`web/scripts/design/lib/prototype.mjs`:

```js
// Opens the prototype in headless Chromium to read its state index and render states (design spec §5, §5.1).
import { chromium } from 'playwright';
import { pathToFileURL } from 'node:url';

export const VIEWPORT = { width: 1440, height: 900 };

// Fallback for prototypes that ignore ?shot=1: hide the design-review chrome.
const HIDE_REVIEW_CHROME = '.review-bar { display: none !important; }';

export async function withBrowser(fn) {
  const browser = await chromium.launch();
  try {
    return await fn(browser);
  } finally {
    await browser.close();
  }
}

export async function readRawStates(browser, indexHtml, timeout = 10_000) {
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(e.message));
  try {
    await page.goto(pathToFileURL(indexHtml).href);
    await page.waitForFunction(() => Array.isArray(window.ST?.STATES), null, { timeout }).catch(() => {
      const detail = errors.length ? `; page errors: ${errors.join('; ')}` : '';
      throw new Error(`window.ST.STATES never appeared in ${indexHtml}${detail}`);
    });
    return await page.evaluate(() =>
      window.ST.STATES.map((s) => ({ id: s.id, group: s.group, ref: s.ref, desc: s.desc, release: s.release ?? null })),
    );
  } finally {
    await page.close();
  }
}

export async function shootState(browser, indexHtml, id, theme, outFile) {
  const context = await browser.newContext({ viewport: VIEWPORT, colorScheme: theme });
  // The Smart Tutor prototype reads its theme from localStorage key st_theme (index.html).
  await context.addInitScript((t) => {
    try {
      localStorage.setItem('st_theme', t);
    } catch {}
  }, theme);
  try {
    const page = await context.newPage();
    await page.goto(`${pathToFileURL(indexHtml).href}?shot=1#/${id}`);
    await page.addStyleTag({ content: HIDE_REVIEW_CHROME });
    await page.waitForTimeout(400);
    await page.screenshot({ path: outFile });
  } finally {
    await context.close();
  }
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd web && npm run test:design`
Expected: PASS, 25 tests.

- [ ] **Step 6: Commit**

```bash
git add web/scripts/design web/package.json web/package-lock.json
git commit -m "Add git and browser adapters for the design tooling"
```

### Task 5: The four commands, Makefile targets, and states.json

**Files:**
- Create: `web/scripts/design/lib/paths.mjs`, `lib/cli.mjs`
- Create: `web/scripts/design/states.mjs`, `accept.mjs`, `shots.mjs`, `diff.mjs`
- Create: `sdd/design/states.json` (generated)
- Modify: `web/package.json` (scripts), `Makefile`

**Interfaces:**
- Consumes: everything from Tasks 1–4.
- Produces: `buildStates(root, protoDir?): Promise<State[]>` (from `states.mjs`), npm scripts `design:states|accept|shots|diff`, Makefile targets `design-states|design-accept|design-shots|design-diff`.

- [ ] **Step 1: Shared paths and CLI helpers**

`web/scripts/design/lib/paths.mjs`:

```js
// Repo-relative paths used by the design tooling (design spec §4).
export const PROTOTYPE = 'sdd/design/prototype';
export const STATES_JSON = 'sdd/design/states.json';
export const ROUNDS_MD = 'sdd/design/rounds.md';
export const BRIEF = 'sdd/design/brief.md';
export const PRD = 'sdd/prd.md';
export const SHOTS = '.design-shots';
```

`web/scripts/design/lib/cli.mjs`:

```js
// Entry-point helpers: run main() only when executed directly, print errors without a stack trace.
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const isMain = (metaUrl) => Boolean(process.argv[1]) && metaUrl === pathToFileURL(resolve(process.argv[1])).href;

export function run(main) {
  main().catch((e) => {
    console.error(`error: ${e.message}`);
    process.exit(1);
  });
}
```

- [ ] **Step 2: `states.mjs`**

```js
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
```

- [ ] **Step 3: `accept.mjs`**

```js
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
```

- [ ] **Step 4: `shots.mjs`**

```js
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
      for (const id of matched) for (const theme of themes) await shootState(browser, index, id, theme, join(outDir, `${id}.${theme}.png`));
      return matched.length * themes.length;
    });
    console.log(`Wrote ${count} screenshots to ${SHOTS}/${label}/`);
  } finally {
    if (tmp) rmSync(tmp, { recursive: true, force: true });
  }
}

if (isMain(import.meta.url)) run(main);
```

- [ ] **Step 5: `diff.mjs`**

```js
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
  const toLabel = values.to || 'working copy';
  console.log(`States from ${values.from} to ${toLabel}:`);
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
```

- [ ] **Step 6: npm scripts and Makefile targets**

`web/package.json` scripts gain:

```json
"design:states": "node scripts/design/states.mjs",
"design:accept": "node scripts/design/accept.mjs",
"design:shots": "node scripts/design/shots.mjs",
"design:diff": "node scripts/design/diff.mjs"
```

`Makefile`: add the four names to `.PHONY` and append:

```make
design-states: ## regenerate sdd/design/states.json from the prototype (design spec §5)
	cd web && npm run design:states
design-accept: ## ROUND=v0.3 [FEEDBACK="Q7, D1–D12"]: record an accepted design round
	cd web && npm run design:accept -- --round "$(ROUND)" --feedback "$(FEEDBACK)"
design-shots:  ## STATES="chat-*" [ROUND=v0.3] [THEME=light|dark|both]: render mockup states to .design-shots/
	cd web && npm run design:shots -- --states "$(STATES)" $(if $(ROUND),--round $(ROUND)) --theme $(or $(THEME),light)
design-diff:   ## FROM=v0.2 [TO=v0.3]: state changes between rounds and the open issues citing them
	cd web && npm run design:diff -- --from "$(FROM)" $(if $(TO),--to $(TO))
```

- [ ] **Step 7: Generate states.json and run each command once**

Run, from the repo root:
- `cd web && npm run design:states` → `Wrote sdd/design/states.json: <n> states`
- `cd web && npm run design:states -- --check` → `sdd/design/states.json is current`
- `cd web && npm run design:shots -- --states "library-empty,chat-fourth-subject-refused" --theme both` → 4 PNGs in `.design-shots/working/`; open one and confirm the review bar is hidden.
- `cd web && npm run design:shots -- --states "chta-*"` → `error: No state matches chta-*`, exit 1.
- `cd web && npm run design:accept -- --round v0.4` → `error: Round v0.4 must match the brief version (v0.3)`, exit 1, no files changed (`git status`).
- `cd web && npm run design:diff -- --from v0.3` → `error: Tag design-v0.3 not found…`, exit 1.

- [ ] **Step 8: Commit**

```bash
git add web/scripts/design web/package.json Makefile sdd/design/states.json
git commit -m "Add design-states, design-accept, design-shots and design-diff"
```

### Task 6: CI check and agent instructions

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `AGENTS.md`
- Modify: `sdd/design/README.md`
- Modify: `sdd/design/brief.md` (§11, Appendix A)

- [ ] **Step 1: CI job** — append to `.github/workflows/ci.yml` under `jobs:`:

```yaml
  design:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npx playwright install --with-deps chromium
      - name: Design tooling tests
        run: npm run test:design
      - name: states.json matches the prototype
        run: npm run design:states -- --check
```

- [ ] **Step 2: `AGENTS.md` "Design inputs"** — insert before "## Commits, PRs, and docs":

```markdown
## Design inputs

The mockups live in `sdd/design/` (brief, prototype, accepted rounds). Process: `sdd/specs/2026-10-03-design-to-code-loop-design.md`.

1. Read the ticket's `## Design` section, then the round's row in `sdd/design/rounds.md`.
2. Render the ticket's states and look at them before writing code: `make design-shots ROUND=v0.3 STATES="chat-*" THEME=both` (PNGs in `.design-shots/`). First time: `cd web && npx playwright install chromium`.
3. The prototype is a spec, not code to copy. Rebuild it with `web/src/components/` and the design tokens; never paste prototype HTML or CSS into a feature.
4. If the mockup and the PRD disagree, follow the PRD and record the conflict in the PR description and the brief's Feedback log.
5. Read the prototype at the ticket's tag (`ROUND=`), not the working copy, which may hold a round in progress. Never read Open Design or its data folder.
6. After changing `sdd/design/prototype/`, run `make design-states`; CI fails when `sdd/design/states.json` is stale.
```

- [ ] **Step 3: `sdd/design/README.md`** — replace the `rounds.md` and `states.json` rows' "Added with the tooling." with their real descriptions, and add a "Commands" section listing the four Makefile targets with one-line descriptions (same text as the Makefile comments).

- [ ] **Step 4: Brief §11 and Appendix A** — add to `sdd/design/brief.md` §11 a numbered item 6:

```markdown
6. A prototype that tools can read (applies from the next round): expose every state in `window.ST.STATES` as `{ id, group, ref, desc }`, open any state at `index.html#/<state-id>`, and hide the design-review chrome when the URL has `?shot=1`.
```

and append to the Appendix A prompt: `Expose every state in window.ST.STATES, open each at index.html#/<state-id>, and hide review chrome when the URL has ?shot=1.`

The brief version stays v0.3: these lines apply to the next round, and the PO bumps the version when the next round starts (brief §13).

- [ ] **Step 5: Verify and commit**

Run: `cd web && npm run test:design && npm run design:states -- --check && npm run build`
Expected: all pass.

```bash
git add .github/workflows/ci.yml AGENTS.md sdd/design/README.md sdd/design/brief.md
git commit -m "Check states.json in CI and add design inputs for agents"
```
