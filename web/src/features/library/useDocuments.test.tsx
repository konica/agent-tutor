import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { useDocuments } from "./useDocuments";

const doc = (id: string): DocumentResponse => ({ document_id: id, title: `${id}.pdf`, state: "processing", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null });

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

afterEach(() => vi.useRealTimers());

describe("useDocuments", () => {
  it("does not start a load while one is running", async () => {
    vi.useFakeTimers();
    const slow = deferred<DocumentResponse[]>();
    const load = vi.fn(() => slow.promise);
    renderHook(() => useDocuments(load, 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3500);
    });
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("keeps the newest result when an older load resolves last", async () => {
    vi.useFakeTimers();
    const first = deferred<DocumentResponse[]>();
    const load = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValue([doc("new")]);
    const { result } = renderHook(() => useDocuments(load, 60000));
    await act(async () => {
      await result.current.refresh(); // second load overlaps the still-running first
    });
    expect(result.current.documents).toEqual([doc("new")]);
    await act(async () => {
      first.resolve([doc("old")]);
    });
    expect(result.current.documents).toEqual([doc("new")]);
  });

  it("sets nothing after unmount", async () => {
    const slow = deferred<DocumentResponse[]>();
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const { unmount } = renderHook(() => useDocuments(() => slow.promise, 1000));
    unmount();
    await act(async () => {
      slow.resolve([doc("a")]);
    });
    expect(error).not.toHaveBeenCalled();
    error.mockRestore();
  });

  it("keeps polling when the caller passes a new load function every render", async () => {
    vi.useFakeTimers();
    const calls = vi.fn(async () => [doc("a")]);
    const { rerender } = renderHook(() => useDocuments(async () => calls(), 1000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    rerender();
    rerender();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(calls).toHaveBeenCalledTimes(1);
  });
});
