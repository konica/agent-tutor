import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";
import { loadMySubjects } from "./subjects";

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
