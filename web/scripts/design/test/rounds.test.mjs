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
