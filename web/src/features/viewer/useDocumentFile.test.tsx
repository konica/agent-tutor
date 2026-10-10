import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DocumentNotFoundError, DocumentNotOpenableError, type DocumentFile, type DocumentResponse } from "../../api/documents";
import { SessionExpiredError } from "../../auth/authClient";
import { useDocumentFile } from "./useDocumentFile";

const doc = (id: string) => ({ id, title: id }) as unknown as DocumentResponse;
const file = (id: string, url: string, expiresAt: number): DocumentFile => ({ url, expiresAt, document: doc(id) });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(0);
});
afterEach(() => vi.useRealTimers());

const flush = () => act(async () => {});

describe("useDocumentFile", () => {
  it("loads, then is ready", async () => {
    const load = vi.fn().mockResolvedValue(file("d1", "u1", 300_000));
    const { result } = renderHook(() => useDocumentFile("d1", load));
    expect(result.current.state).toEqual({ status: "loading" });
    await flush();
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "u1" } });
    expect(load).toHaveBeenCalledWith("d1");
  });

  it("renews the link 30s before it expires", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(file("d1", "u1", 300_000))
      .mockResolvedValueOnce(file("d1", "u2", 600_000));
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(269_000);
    });
    expect(load).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "u2" } });
  });

  it("keeps the old link when renewal fails", async () => {
    const load = vi.fn().mockResolvedValueOnce(file("d1", "u1", 300_000)).mockRejectedValueOnce(new Error("x"));
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(271_000);
    });
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "u1" } });
  });

  it.each([
    [new DocumentNotFoundError("gone"), "not-found"],
    [new DocumentNotOpenableError("busy"), "not-openable"],
    [new Error("boom"), "error"],
  ])("maps %s to %s", async (error, reason) => {
    const load = vi.fn().mockRejectedValue(error);
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    expect(result.current.state).toEqual({ status: "failed", reason });
  });

  it("stays loading when the session expired", async () => {
    const load = vi.fn().mockRejectedValue(new SessionExpiredError());
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    expect(result.current.state).toEqual({ status: "loading" });
  });

  it("retry asks for a new link, even right after a failure", async () => {
    const load = vi.fn().mockRejectedValueOnce(new Error("x")).mockResolvedValueOnce(file("d1", "u2", 300_000));
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    expect(result.current.state).toMatchObject({ status: "failed" });
    act(() => result.current.retry());
    expect(result.current.state).toEqual({ status: "loading" });
    await flush();
    expect(load).toHaveBeenCalledTimes(2);
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "u2" } });
  });

  it("ignores a late reply for a previous document", async () => {
    let resolveOld!: (f: DocumentFile) => void;
    const load = vi.fn((id: string) =>
      id === "old" ? new Promise<DocumentFile>((r) => (resolveOld = r)) : Promise.resolve(file("new", "unew", 300_000)),
    );
    const { result, rerender } = renderHook(({ id }) => useDocumentFile(id, load), { initialProps: { id: "old" } });
    rerender({ id: "new" });
    await flush();
    await act(async () => resolveOld(file("old", "uold", 300_000)));
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "unew" } });
  });

  it("does not refetch when the caller passes a new load function each render", async () => {
    const calls = vi.fn().mockResolvedValue(file("d1", "u1", 300_000));
    const { rerender } = renderHook(() => useDocumentFile("d1", (id) => calls(id)));
    await flush();
    rerender();
    await flush();
    expect(calls).toHaveBeenCalledTimes(1);
  });

  it("setDocument replaces the document on the file", async () => {
    const load = vi.fn().mockResolvedValue(file("d1", "u1", 300_000));
    const { result } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    act(() => result.current.setDocument({ ...doc("d1"), title: "Restored" } as DocumentResponse));
    expect(result.current.state).toMatchObject({ status: "ready", file: { url: "u1", document: { title: "Restored" } } });
  });

  it("clears the renewal timer on unmount", async () => {
    const load = vi.fn().mockResolvedValue(file("d1", "u1", 300_000));
    const { unmount } = renderHook(() => useDocumentFile("d1", load));
    await flush();
    unmount();
    await vi.advanceTimersByTimeAsync(400_000);
    expect(load).toHaveBeenCalledTimes(1);
  });
});
