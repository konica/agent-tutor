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
