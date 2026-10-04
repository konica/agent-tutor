import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";
import { loadMe } from "./me";

function setup({ status = 200, getToken = async () => "t", fail = false } = {}) {
  const fetch = vi.fn(async (_input: RequestInfo | URL) => {
    if (fail) throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify({ user_id: "u1", name: "Ada Lovelace", roles: ["learner"] }), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  });
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken, onUnauthorized: vi.fn(), apiClient });
  return apiClient;
}

describe("loadMe", () => {
  it("returns the learner on 200", async () => {
    await expect(loadMe(setup())).resolves.toMatchObject({ name: "Ada Lovelace" });
  });

  it("rejects with SessionExpiredError on 401", async () => {
    await expect(loadMe(setup({ status: 401 }))).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with SessionExpiredError when the token can't be refreshed", async () => {
    const apiClient = setup({ getToken: () => Promise.reject(new Error("refresh failed")) });
    await expect(loadMe(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain error when the API can't be reached", async () => {
    const error = await loadMe(setup({ fail: true })).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(SessionExpiredError);
  });
});
