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
