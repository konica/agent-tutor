import { describe, expect, it } from "vitest";

import { followColorScheme } from "./theme";

function fakeQuery(matches: boolean) {
  const listeners = new Set<(e: MediaQueryListEvent) => void>();
  const query = {
    matches,
    addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) => listeners.delete(fn),
  } as unknown as MediaQueryList;
  const change = (dark: boolean) => listeners.forEach((fn) => fn({ matches: dark } as MediaQueryListEvent));
  return { query, change, listeners };
}

describe("followColorScheme", () => {
  it("sets the current OS theme", () => {
    const root = document.createElement("html");
    followColorScheme(root, fakeQuery(true).query);
    expect(root.dataset.theme).toBe("dark");
    followColorScheme(root, fakeQuery(false).query);
    expect(root.dataset.theme).toBe("light");
  });

  it("follows later changes", () => {
    const root = document.createElement("html");
    const fake = fakeQuery(false);
    followColorScheme(root, fake.query);
    fake.change(true);
    expect(root.dataset.theme).toBe("dark");
  });

  it("stops following after unsubscribe", () => {
    const root = document.createElement("html");
    const fake = fakeQuery(false);
    const stop = followColorScheme(root, fake.query);
    stop();
    fake.change(true);
    expect(root.dataset.theme).toBe("light");
    expect(fake.listeners.size).toBe(0);
  });
});
