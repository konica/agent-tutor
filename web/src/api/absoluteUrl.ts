/** Resolves a configured URL against the page's origin, so one build can use same-origin paths such as "/api". */
export function absoluteUrl(url: string, origin: string = window.location.origin): string {
  return new URL(url, origin).href.replace(/\/$/, "");
}
