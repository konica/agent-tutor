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
