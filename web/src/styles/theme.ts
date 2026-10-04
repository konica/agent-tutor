// The app follows the OS colour scheme; a theme switch in the user menu comes later (DESIGN.md → Themes).
export function followColorScheme(root: HTMLElement, query: MediaQueryList): () => void {
  const apply = (dark: boolean) => {
    root.dataset.theme = dark ? "dark" : "light";
  };
  const onChange = (e: MediaQueryListEvent) => apply(e.matches);
  apply(query.matches);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
