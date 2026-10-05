import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { loadDocuments, uploadPdf } from "./documents";
import { createClient, createConfig } from "./generated/client";

function api(handler: (request: Request) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return { apiClient, fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("loadDocuments", () => {
  it("returns the caller's documents", async () => {
    const doc = { document_id: "d1", title: "a.pdf", state: "processing", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [] };
    const { apiClient } = api(() => json([doc]));
    await expect(loadDocuments(apiClient)).resolves.toEqual([doc]);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadDocuments(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});

describe("uploadPdf", () => {
  const started = { document_id: "d1", upload_id: "u1", url: "http://s3.test/bucket", fields: { key: "uploads/ada/u1.pdf", policy: "p" } };

  it("asks for a presigned POST with the file name, then posts the fields and the file last", async () => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response(null, { status: 204 }));
    const file = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await uploadPdf(file, apiClient, post);

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/uploads");
    expect(await request.json()).toEqual({ file_name: "paper.pdf" });
    const [url, init] = post.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).toBe("http://s3.test/bucket");
    const form = init.body as FormData;
    expect([...form.keys()]).toEqual(["key", "policy", "file"]);
    expect(form.get("file")).toBe(file);
  });

  it.each([
    ["empty", 0],
    ["oversized", 52_428_801],
  ])("rejects an %s file without calling the API", async (_label, size) => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn();
    const file = new File(["x"], "x.pdf");
    Object.defineProperty(file, "size", { value: size });
    await expect(uploadPdf(file, apiClient, post)).rejects.toThrow();
    expect(fetch).not.toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });

  it("accepts a file of exactly 50 MiB", async () => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response(null, { status: 204 }));
    const file = new File(["x"], "x.pdf");
    Object.defineProperty(file, "size", { value: 52_428_800 });
    await uploadPdf(file, apiClient, post);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects when S3 refuses the file", async () => {
    const { apiClient } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response("<Error/>", { status: 403 }));
    await expect(uploadPdf(new File(["x"], "x.pdf"), apiClient, post)).rejects.toThrow("403");
  });
});
