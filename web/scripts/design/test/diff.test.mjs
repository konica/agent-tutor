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
