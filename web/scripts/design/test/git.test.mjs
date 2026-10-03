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
  run('config', 'core.autocrlf', 'false');
  mkdirSync(join(repo, 'sdd/design/prototype/js'), { recursive: true });
  writeFileSync(join(repo, 'sdd/design/prototype/index.html'), '<p>v0.3</p>\r\n');
  writeFileSync(join(repo, 'sdd/design/prototype/js/a.js'), 'a');
  writeFileSync(join(repo, 'sdd/design/states.json'), '[]\n');
  run('add', '.');
  run('commit', '-qm', 'round');
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
