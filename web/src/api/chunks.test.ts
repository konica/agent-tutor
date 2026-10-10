import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { ChunkNotFoundError, loadChunk, recordHighlightMiss } from "./chunks";
import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";

function api(handler: (request: Request) => Response | Promise<Response>) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return { apiClient, fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("loadChunk", () => {
  it("GETs the chunk and maps it to camelCase", async () => {
    const { apiClient, fetch } = api(() => json({ chunk_id: "c1", document_id: "d1", page: 3, start_index: 120, text: "Cited text." }));
    await expect(loadChunk("c1", apiClient)).resolves.toEqual({ chunkId: "c1", documentId: "d1", page: 3, startIndex: 120, text: "Cited text." });
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.method).toBe("GET");
    expect(new URL(request.url).pathname).toBe("/chunks/c1");
  });

  it("keeps a null page and start_index", async () => {
    const { apiClient } = api(() => json({ chunk_id: "c1", document_id: "d1", page: null, start_index: null, text: "x" }));
    await expect(loadChunk("c1", apiClient)).resolves.toMatchObject({ page: null, startIndex: null });
  });

  it("rejects with ChunkNotFoundError on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Chunk not found" }, 404));
    await expect(loadChunk("c1", apiClient)).rejects.toBeInstanceOf(ChunkNotFoundError);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadChunk("c1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain error on other failures", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    const error = await loadChunk("c1", apiClient).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(ChunkNotFoundError);
  });
});

describe("recordHighlightMiss", () => {
  it("POSTs to /viewer/highlight-misses", async () => {
    const { apiClient, fetch } = api(() => new Response(null, { status: 204 }));
    recordHighlightMiss(apiClient);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const request = fetch.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe("/viewer/highlight-misses");
  });

  // Vitest fails the run on an unhandled rejection, so a swallowed error is one that never surfaces here.
  it("never throws when the request fails", async () => {
    const { apiClient, fetch } = api(() => Promise.reject(new TypeError("offline")));
    expect(() => recordHighlightMiss(apiClient)).not.toThrow();
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    const { apiClient: failing, fetch: failingFetch } = api(() => json({ detail: "boom" }, 500));
    expect(() => recordHighlightMiss(failing)).not.toThrow();
    await vi.waitFor(() => expect(failingFetch).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 0));
  });
});
