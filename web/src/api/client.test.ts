import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { apiBaseUrl, configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";
import { getMe } from "./generated/sdk.gen";

function setup(status: number, getToken: () => Promise<string> = async () => "access-token") {
  const fetch = vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response(JSON.stringify({ user_id: "u1", name: "Ada Lovelace", roles: ["learner"] }), {
        status,
        headers: { "Content-Type": "application/json" },
      }),
  );
  const apiClient = createClient(createConfig({ fetch }));
  const onUnauthorized = vi.fn();
  configureApiClient({ baseUrl: "http://api.test", getToken, onUnauthorized, apiClient });
  return { apiClient, fetch, onUnauthorized };
}

describe("API client", () => {
  afterEach(() => vi.unstubAllEnvs());

  it("calls the API on the page's origin when built with VITE_API_URL=/api", () => {
    vi.stubEnv("VITE_API_URL", "/api");
    expect(apiBaseUrl()).toBe(`${window.location.origin}/api`);
  });

  it("falls back to the local API when VITE_API_URL is empty", () => {
    vi.stubEnv("VITE_API_URL", "");
    expect(apiBaseUrl()).toBe("http://localhost:10450");
  });

  it("sends a fresh bearer token", async () => {
    const { apiClient, fetch } = setup(200);
    const { data } = await getMe({ client: apiClient });
    expect(data?.name).toBe("Ada Lovelace");
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/me");
    expect(request.headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("reports a 401", async () => {
    const { apiClient, onUnauthorized } = setup(401);
    await getMe({ client: apiClient });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("getToken failure notifies and sends nothing", async () => {
    const { apiClient, fetch, onUnauthorized } = setup(200, () => Promise.reject(new Error("refresh failed")));
    await expect(getMe({ client: apiClient, throwOnError: true })).rejects.toBeInstanceOf(SessionExpiredError);
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
  });
});
