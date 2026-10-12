import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConversationFilters, ThreadSummaryResponse } from "../../api/conversations";
import { useFilteredConversations } from "./useFilteredConversations";

const row = (id: string): ThreadSummaryResponse => ({ thread_id: id, title: id, subjects: [], documents: 1, last_activity: "2026-09-30T03:00:00Z" });
const tick = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useFilteredConversations", () => {
  it("does not load without filters", async () => {
    const load = vi.fn(async () => [row("a")]);
    const { result } = renderHook(() => useFilteredConversations(load, {}, null));
    await tick(500);
    expect(load).not.toHaveBeenCalled();
    expect(result.current).toEqual({ list: null, failed: false });
  });

  it("does not load for a blank search", async () => {
    const load = vi.fn(async () => [row("a")]);
    renderHook(() => useFilteredConversations(load, { q: "  " }, null));
    await tick(500);
    expect(load).not.toHaveBeenCalled();
  });

  it("loads once with the filters and exposes the result", async () => {
    const load = vi.fn(async () => [row("a")]);
    const filters = { subject_id: "s1" };
    const { result } = renderHook(() => useFilteredConversations(load, filters, null));
    await tick(0);
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith(filters);
    expect(result.current.list).toEqual([row("a")]);
  });

  it("never lets a slow older response replace a newer one", async () => {
    let resolveSlow!: (v: ThreadSummaryResponse[]) => void;
    const load = vi.fn((f: ConversationFilters) =>
      f.subject_id === "s1" ? new Promise<ThreadSummaryResponse[]>((r) => { resolveSlow = r; }) : Promise.resolve([row("fast")]),
    );
    const { result, rerender } = renderHook(({ f }) => useFilteredConversations(load, f, null), { initialProps: { f: { subject_id: "s1" } as ConversationFilters } });
    await tick(0);
    rerender({ f: { subject_id: "s2" } });
    await tick(0);
    expect(result.current.list).toEqual([row("fast")]);
    await act(async () => { resolveSlow([row("slow")]); await vi.advanceTimersByTimeAsync(0); });
    expect(result.current.list).toEqual([row("fast")]);
  });

  it("debounces the title search", async () => {
    const load = vi.fn(async () => [row("a")]);
    const { rerender } = renderHook(({ q }) => useFilteredConversations(load, { q }, null), { initialProps: { q: "r" } });
    await tick(100);
    rerender({ q: "ra" });
    await tick(100);
    rerender({ q: "rag" });
    await tick(300);
    expect(load).toHaveBeenCalledTimes(1);
    expect(load).toHaveBeenCalledWith({ q: "rag" });
  });

  it("reloads when the reload key changes", async () => {
    const load = vi.fn(async () => [row("a")]);
    const { rerender } = renderHook(({ k }) => useFilteredConversations(load, { subject_id: "s1" }, k), { initialProps: { k: 1 } });
    await tick(0);
    rerender({ k: 2 });
    await tick(0);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("reports a failed load", async () => {
    const load = vi.fn(async () => { throw new Error("boom"); });
    const { result } = renderHook(() => useFilteredConversations(load, { subject_id: "s1" }, null));
    await tick(0);
    expect(result.current.failed).toBe(true);
  });
});
