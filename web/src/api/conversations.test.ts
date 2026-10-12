import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { archiveConversation, listConversations, restoreConversation } from "./conversations";
import { createClient, createConfig } from "./generated/client";

function api(handler: (request: Request) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return { apiClient, fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("listConversations", () => {
  it("returns the learner's conversations", async () => {
    const row = { thread_id: "t1", title: "What is attention?", subjects: [], documents: 1, last_activity: "2026-10-11T02:48:00Z" };
    const { apiClient, fetch } = api(() => json([row]));
    await expect(listConversations({}, apiClient)).resolves.toEqual([row]);
    expect(new URL((fetch.mock.calls[0]![0] as Request).url).pathname).toBe("/threads");
  });

  it("sends the filters, trimming the title search", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await listConversations({ subject_id: "s1", active_from: "2026-10-01", active_to: "2026-10-05", q: " rag " }, apiClient);
    const url = new URL((fetch.mock.calls[0]![0] as Request).url);
    expect(url.pathname + url.search).toBe("/threads?subject_id=s1&active_from=2026-10-01&active_to=2026-10-05&q=rag");
  });

  it("sends no query for a blank search", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await listConversations({ q: "  " }, apiClient);
    const url = new URL((fetch.mock.calls[0]![0] as Request).url);
    expect(url.pathname + url.search).toBe("/threads");
  });

  it("throws SessionExpiredError when the session is over", async () => {
    const { apiClient } = api(() => json({ detail: "Unauthorized" }, 401));
    await expect(listConversations({}, apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("names the request when it fails", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    await expect(listConversations({}, apiClient)).rejects.toThrow(/GET \/threads/);
  });
});

describe("listConversations archived", () => {
  it("asks for the archived ones", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await listConversations({ archived: true }, apiClient);
    const url = new URL((fetch.mock.calls[0]![0] as Request).url);
    expect(url.pathname + url.search).toBe("/threads?archived=true");
  });

  it("narrows the archived ones by the filters too", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await listConversations({ archived: true, q: "rag" }, apiClient);
    const url = new URL((fetch.mock.calls[0]![0] as Request).url);
    expect(url.pathname + url.search).toBe("/threads?archived=true&q=rag");
  });
});

describe.each([
  ["archiveConversation", archiveConversation, "archive"],
  ["restoreConversation", restoreConversation, "restore"],
] as const)("%s", (_name, call, verb) => {
  const body = { thread_id: "t1", title: "T", status: verb === "archive" ? "archived" : "active" };

  it("posts to the thread and returns the body", async () => {
    const { apiClient, fetch } = api(() => json(body));
    await expect(call("t1", apiClient)).resolves.toEqual(body);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(new URL(request.url).pathname).toBe(`/threads/t1/${verb}`);
  });

  it("throws SessionExpiredError when the session is over", async () => {
    const { apiClient } = api(() => json({ detail: "Unauthorized" }, 401));
    await expect(call("t1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("throws an Error when the conversation is not found", async () => {
    const { apiClient } = api(() => json({ detail: "Not found" }, 404));
    const error = await call("t1", apiClient).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(SessionExpiredError);
  });
});
