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
