const lastName = (name: string) => name.trim().split(/\s+/).at(-1) ?? "";

// "Schick et al. · 2023": one author in full, two as "Last and Last", three or more as "Last et al."; the year follows; nothing when both are missing.
export function byline(authors: string[], year: number | null): string {
  const names = authors.filter((a) => a.trim());
  let who = "";
  if (names.length === 1) who = names[0].trim();
  else if (names.length === 2) who = `${lastName(names[0])} and ${lastName(names[1])}`;
  else if (names.length > 2) who = `${lastName(names[0])} et al.`;
  return [who, year === null ? "" : String(year)].filter(Boolean).join(" · ");
}
