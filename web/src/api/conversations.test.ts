import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { listConversations } from "./conversations";
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
    await expect(listConversations(apiClient)).resolves.toEqual([row]);
    expect(new URL((fetch.mock.calls[0]![0] as Request).url).pathname).toBe("/threads");
  });

  it("throws SessionExpiredError when the session is over", async () => {
    const { apiClient } = api(() => json({ detail: "Unauthorized" }, 401));
    await expect(listConversations(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("names the request when it fails", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    await expect(listConversations(apiClient)).rejects.toThrow(/GET \/threads/);
  });
});
