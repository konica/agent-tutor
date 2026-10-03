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
