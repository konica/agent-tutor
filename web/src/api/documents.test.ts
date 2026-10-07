import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { findInLibrary, loadDocuments, loadUploadLimits, rejectionReason, RetriesUsedUpError, retryProcessing, sha256Hex, uploadPdf } from "./documents";
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
    const doc = { document_id: "d1", title: "a.pdf", state: "processing", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false };
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

  it("rejects when S3 refuses the file", async () => {
    const { apiClient } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response("<Error/>", { status: 403 }));
    await expect(uploadPdf(new File(["x"], "x.pdf"), apiClient, post)).rejects.toThrow("403");
  });
});

describe("rejectionReason", () => {
  const limits = { max_bytes: 52_428_800, max_pages: 500 };
  const file = (name: string, type: string, size = 10) => {
    const f = new File(["x"], name, { type });
    Object.defineProperty(f, "size", { value: size });
    return f;
  };

  it("accepts a PDF by type, or by a .pdf name when the browser gives no type", () => {
    expect(rejectionReason(file("a.pdf", "application/pdf"), limits)).toBeNull();
    expect(rejectionReason(file("B.PDF", ""), limits)).toBeNull();
  });

  it("refuses other types", () => {
    expect(rejectionReason(file("reading-list.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), limits))
      .toBe("Not uploaded. Only PDF files can be uploaded.");
    expect(rejectionReason(file("notes.txt", ""), limits)).toBe("Not uploaded. Only PDF files can be uploaded.");
  });

  it("still refuses a non-PDF and an empty file when the limits are unknown, and skips only the size check", () => {
    expect(rejectionReason(file("notes.docx", "application/msword"), null)).toBe("Not uploaded. Only PDF files can be uploaded.");
    expect(rejectionReason(file("a.pdf", "application/pdf", 0), null)).toBe("Not uploaded. This file is empty.");
    expect(rejectionReason(file("big.pdf", "application/pdf", 72 * 1_048_576), null)).toBeNull();
  });

  it("refuses an empty file", () => {
    expect(rejectionReason(file("a.pdf", "application/pdf", 0), limits)).toBe("Not uploaded. This file is empty.");
  });

  it("refuses a file over the limit and never shows it as equal to the limit", () => {
    expect(rejectionReason(file("big.pdf", "application/pdf", 72 * 1_048_576), limits))
      .toBe("Not uploaded. This file is 72 MB; the limit is 50 MB.");
    expect(rejectionReason(file("edge.pdf", "application/pdf", 52_428_801), limits))
      .toBe("Not uploaded. This file is 50.1 MB; the limit is 50 MB.");
    expect(rejectionReason(file("ok.pdf", "application/pdf", 52_428_800), limits)).toBeNull();
  });
});

describe("loadUploadLimits", () => {
  it("returns the limits", async () => {
    const { apiClient } = api(() => json({ max_bytes: 1, max_pages: 2 }));
    await expect(loadUploadLimits(apiClient)).resolves.toEqual({ max_bytes: 1, max_pages: 2 });
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadUploadLimits(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});

describe("retryProcessing", () => {
  it("POSTs to the document's retry path and resolves on 204", async () => {
    const { apiClient, fetch } = api(() => new Response(null, { status: 204 }));
    await expect(retryProcessing("d3", apiClient)).resolves.toBeUndefined();
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("http://api.test/documents/d3/retry");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(retryProcessing("d3", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with RetriesUsedUpError on 409", async () => {
    const { apiClient } = api(() => json({ detail: "no" }, 409));
    await expect(retryProcessing("d3", apiClient)).rejects.toBeInstanceOf(RetriesUsedUpError);
  });

  it("rejects with an Error on 500", async () => {
    const { apiClient } = api(() => json({ detail: "no" }, 500));
    const rejection = retryProcessing("d3", apiClient);
    await expect(rejection).rejects.toThrow("500");
    await expect(rejection).rejects.not.toBeInstanceOf(RetriesUsedUpError);
  });
});

const ABC_SHA = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad";

describe("sha256Hex", () => {
  it("hashes the file's bytes as lowercase hex", async () => {
    expect(await sha256Hex(new File(["abc"], "a.pdf"))).toBe(ABC_SHA);
  });
});

describe("findInLibrary", () => {
  const file = new File(["abc"], "a.pdf", { type: "application/pdf" });

  it("posts the hash and returns the caller's document id", async () => {
    const { apiClient, fetch } = api(() => json({ document_id: "d1" }));
    await expect(findInLibrary(file, apiClient)).resolves.toBe("d1");
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/documents/duplicate-check");
    expect(await request.json()).toEqual({ sha256: ABC_SHA });
  });

  it("returns null when the file isn't in the library", async () => {
    const { apiClient } = api(() => json({ document_id: null }));
    await expect(findInLibrary(file, apiClient)).resolves.toBeNull();
  });

  it("throws SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(findInLibrary(file, apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("throws on other failures", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    await expect(findInLibrary(file, apiClient)).rejects.toThrow("500");
  });
});
