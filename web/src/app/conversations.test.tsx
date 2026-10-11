import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ThreadSummaryResponse } from "../api/conversations";
import { recentConversations, useConversationsState } from "./conversations";

const thread = (id: string, title: string | null = `Title ${id}`): ThreadSummaryResponse => ({
  thread_id: id,
  title,
  subjects: [],
  documents: 1,
  last_activity: "2026-10-11T02:48:00Z",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("useConversationsState", () => {
  it("loads the list for each key and refreshes on demand", async () => {
    const a = thread("a");
    const load = vi.fn(async () => [a]);
    const { result, rerender } = renderHook(({ key }) => useConversationsState(load, key), { initialProps: { key: "x" } });
    expect(result.current.list).toBeNull();
    await waitFor(() => expect(result.current.list).toEqual([a]));
    expect(load).toHaveBeenCalledTimes(1);
    rerender({ key: "y" });
    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    act(() => result.current.refresh());
    await waitFor(() => expect(load).toHaveBeenCalledTimes(3));
  });

  it("a stale load doesn't overwrite a newer one", async () => {
    const p1 = deferred<ThreadSummaryResponse[]>();
    const p2 = deferred<ThreadSummaryResponse[]>();
    const load = vi.fn().mockReturnValueOnce(p1.promise).mockReturnValueOnce(p2.promise);
    const { result } = renderHook(() => useConversationsState(load, "x"));
    act(() => result.current.refresh());
    expect(load).toHaveBeenCalledTimes(2);
    const b = thread("b");
    await act(async () => p2.resolve([b]));
    await act(async () => p1.resolve([thread("a")]));
    expect(result.current.list).toEqual([b]);
  });

  it("a failed first load sets failed and keeps list null; a later success clears failed", async () => {
    const a = thread("a");
    const load = vi.fn().mockRejectedValueOnce(new Error("down")).mockResolvedValueOnce([a]);
    const { result } = renderHook(() => useConversationsState(load, "x"));
    await waitFor(() => expect(result.current.failed).toBe(true));
    expect(result.current.list).toBeNull();
    act(() => result.current.refresh());
    await waitFor(() => expect(result.current.list).toEqual([a]));
    expect(result.current.failed).toBe(false);
  });
});

describe("recentConversations", () => {
  it("keeps three, newest first as given, with chat paths and untitled fallback", () => {
    const [t1, t2, t3, t4] = [thread("1"), thread("2"), thread("3"), thread("4")] as [
      ThreadSummaryResponse,
      ThreadSummaryResponse,
      ThreadSummaryResponse,
      ThreadSummaryResponse,
    ];
    expect(recentConversations([t1, t2, { ...t3, title: null }, t4])).toEqual([
      { id: "1", title: t1.title, path: "/chat/1" },
      { id: "2", title: t2.title, path: "/chat/2" },
      { id: "3", title: "Untitled conversation", path: "/chat/3" },
    ]);
    expect(recentConversations(null)).toEqual([]);
  });
});
