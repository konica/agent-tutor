import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePanelOpen } from "./usePanelOpen";

const KEY = "smart-tutor.chat-panel-open";

beforeEach(() => localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("usePanelOpen", () => {
  it("starts open", () => {
    const { result } = renderHook(() => usePanelOpen());
    expect(result.current[0]).toBe(true);
  });

  it("toggles and remembers the choice", () => {
    const { result } = renderHook(() => usePanelOpen());
    act(() => result.current[1]());
    expect(result.current[0]).toBe(false);
    expect(localStorage.getItem(KEY)).toBe("false");
    act(() => result.current[1]());
    expect(result.current[0]).toBe(true);
    expect(localStorage.getItem(KEY)).toBe("true");
  });

  it("starts closed when closed was remembered", () => {
    localStorage.setItem(KEY, "false");
    const { result } = renderHook(() => usePanelOpen());
    expect(result.current[0]).toBe(false);
  });

  it("works without storage", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { result } = renderHook(() => usePanelOpen());
    expect(result.current[0]).toBe(true);
    act(() => result.current[1]());
    expect(result.current[0]).toBe(false);
  });
});
