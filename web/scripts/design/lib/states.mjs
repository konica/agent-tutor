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
