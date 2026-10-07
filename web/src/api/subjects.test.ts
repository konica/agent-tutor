import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";
import { loadMySubjects, searchCatalog } from "./subjects";

function setup({ status = 200, fail = false } = {}) {
  const fetch = vi.fn(async (_input: RequestInfo | URL) => {
    if (fail) throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(status === 200 ? [{ subject_id: "s1", name: "LLMs" }] : { detail: "x" }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return apiClient;
}

function api(handler: (request: Request) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return { apiClient, fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("loadMySubjects", () => {
  it("returns the subjects on 200", async () => {
    await expect(loadMySubjects(setup())).resolves.toEqual([{ subject_id: "s1", name: "LLMs" }]);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    await expect(loadMySubjects(setup({ status: 401 }))).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain error on 500", async () => {
    const error = await loadMySubjects(setup({ status: 500 })).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain error when the API can't be reached", async () => {
    await expect(loadMySubjects(setup({ fail: true }))).rejects.toBeInstanceOf(Error);
  });
});

describe("searchCatalog", () => {
  const matches = [
    { subject_id: "s1", name: "Retrieval-Augmented Generation", origin: "yours" },
    { subject_id: "s2", name: "Information Retrieval", origin: "shared" },
  ];

  it("returns the matches and sends the query", async () => {
    const { apiClient, fetch } = api(() => json(matches));
    await expect(searchCatalog("retriev", apiClient)).resolves.toEqual(matches);
    const url = new URL((fetch.mock.calls[0]![0] as Request).url);
    expect(url.pathname).toBe("/subjects/search");
    expect(url.searchParams.get("q")).toBe("retriev");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(searchCatalog("retriev", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with the server's validation message on 422", async () => {
    const { apiClient } = api(() => json({ detail: [{ msg: "String should have at most 100 characters" }] }, 422));
    await expect(searchCatalog("x", apiClient)).rejects.toThrow("String should have at most 100 characters");
  });
});
