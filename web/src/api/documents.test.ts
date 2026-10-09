import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import {
  archiveDocument,
  DocumentGoneError,
  deleteDocument,
  DocumentNotFoundError,
  DocumentNotOpenableError,
  DocumentProcessingError,
  findInLibrary,
  loadDocumentFile,
  loadDocuments,
  loadSubjectSuggestions,
  loadUploadLimits,
  loadUploadStatus,
  postForm,
  rejectionReason,
  restoreDocument,
  RetriesUsedUpError,
  retryProcessing,
  saveSubjects,
  sha256Hex,
  uploadPdf,
} from "./documents";
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
    await expect(loadDocuments({}, apiClient)).resolves.toEqual([doc]);
  });

  it("maps filters to the query and sends none when there are none", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await loadDocuments({}, apiClient);
    expect(new URL((fetch.mock.calls[0][0] as Request).url).search).toBe("");
    await loadDocuments({ subject_ids: ["s1", "s2"], state: "awaiting_subjects", uploaded_from: "2026-10-01", uploaded_to: "2026-10-07" }, apiClient);
    const url = new URL((fetch.mock.calls[1][0] as Request).url);
    expect(url.searchParams.getAll("subject_id")).toEqual(["s1", "s2"]);
    expect(url.searchParams.getAll("state")).toEqual(["awaiting_subjects"]);
    expect(url.searchParams.get("uploaded_from")).toBe("2026-10-01");
    expect(url.searchParams.get("uploaded_to")).toBe("2026-10-07");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadDocuments({}, apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("asks for the archived list only when archived is true", async () => {
    const { apiClient, fetch } = api(() => json([]));
    await loadDocuments({ archived: true }, apiClient);
    expect(new URL((fetch.mock.calls[0][0] as Request).url).searchParams.get("archived")).toBe("true");
    await loadDocuments({ archived: false }, apiClient);
    expect(new URL((fetch.mock.calls[1][0] as Request).url).search).toBe("");
  });
});

describe.each([
  ["archiveDocument", archiveDocument, "archive"],
  ["restoreDocument", restoreDocument, "restore"],
] as const)("%s", (_name, call, action) => {
  const doc = { document_id: "d3", title: "a.pdf", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null, archived: action === "archive" };

  it(`POSTs to the document's ${action} path and returns the document`, async () => {
    const { apiClient, fetch } = api(() => json(doc));
    await expect(call("d3", apiClient)).resolves.toEqual(doc);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe(`http://api.test/documents/d3/${action}`);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(call("d3", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with an Error on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    const rejection = call("d3", apiClient);
    await expect(rejection).rejects.toThrow("Document not found");
    await expect(rejection).rejects.not.toBeInstanceOf(SessionExpiredError);
  });
});

describe("uploadPdf", () => {
  const started = { document_id: "d1", upload_id: "u1", url: "http://s3.test/bucket", fields: { key: "uploads/ada/u1.pdf", policy: "p" } };

  it("asks for a presigned POST with the file name, then posts the fields and the file last", async () => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn(async () => 204);
    const file = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await uploadPdf(file, {}, apiClient, post);

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/uploads");
    expect(await request.json()).toEqual({ file_name: "paper.pdf" });
    const [url, form] = post.mock.calls[0]! as unknown as [string, FormData];
    expect(url).toBe("http://s3.test/bucket");
    expect([...form.keys()]).toEqual(["key", "policy", "file"]);
    expect(form.get("file")).toBe(file);
  });

  it("reports the new document and upload ids, then the progress, then 1 when storage accepts the file", async () => {
    const { apiClient } = api(() => json(started, 201));
    const seen: string[] = [];
    const post = vi.fn(async (_url: string, _form: FormData, onProgress: (f: number) => void) => {
      onProgress(0.5);
      return 204;
    });
    await uploadPdf(new File(["%PDF"], "p.pdf"), { onStarted: (id, uploadId) => seen.push(`started ${id} ${uploadId}`), onProgress: (f) => seen.push(`progress ${f}`) }, apiClient, post);
    expect(seen).toEqual(["started d1 u1", "progress 0.5", "progress 1"]);
  });

  it("rejects when S3 refuses the file, and never reports 1", async () => {
    const { apiClient } = api(() => json(started, 201));
    const onProgress = vi.fn();
    await expect(uploadPdf(new File(["x"], "x.pdf"), { onProgress }, apiClient, async () => 403)).rejects.toThrow("403");
    expect(onProgress).not.toHaveBeenCalledWith(1);
  });
});

describe("loadUploadStatus", () => {
  it("asks what became of the upload and returns the answer", async () => {
    const body = { upload_id: "u1", outcome: "duplicate", document_id: "d1", archived: false };
    const { apiClient, fetch } = api(() => json(body));
    await expect(loadUploadStatus("u1", apiClient)).resolves.toEqual(body);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("GET");
    expect(request.url).toBe("http://api.test/uploads/u1");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadUploadStatus("u1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with the status otherwise", async () => {
    const { apiClient } = api(() => json({ detail: "Not found" }, 404));
    await expect(loadUploadStatus("u1", apiClient)).rejects.toThrow("404");
  });
});

describe("postForm", () => {
  class FakeXhr {
    static last: FakeXhr;
    upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    status = 0;
    method = "";
    url = "";
    body: unknown = null;
    constructor() {
      FakeXhr.last = this;
    }
    open(method: string, url: string) {
      this.method = method;
      this.url = url;
    }
    send(body: unknown) {
      this.body = body;
    }
  }

  afterEach(() => vi.unstubAllGlobals());

  it("posts the form and reports the fraction sent, then resolves with the status", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const form = new FormData();
    const onProgress = vi.fn();
    const sent = postForm("http://s3.test/bucket", form, onProgress);
    const xhr = FakeXhr.last;
    expect([xhr.method, xhr.url, xhr.body]).toEqual(["POST", "http://s3.test/bucket", form]);
    xhr.upload.onprogress!({ lengthComputable: true, loaded: 25, total: 100 });
    xhr.upload.onprogress!({ lengthComputable: false, loaded: 0, total: 0 });
    xhr.status = 204;
    xhr.onload!();
    await expect(sent).resolves.toBe(204);
    expect(onProgress.mock.calls).toEqual([[0.25]]);
  });

  it("rejects on a network error", async () => {
    vi.stubGlobal("XMLHttpRequest", FakeXhr);
    const sent = postForm("http://s3.test/bucket", new FormData(), vi.fn());
    FakeXhr.last.onerror!();
    await expect(sent).rejects.toThrow("Upload to storage failed");
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

describe("loadSubjectSuggestions", () => {
  const suggestions = {
    document_id: "d1",
    title: "a.pdf",
    summary: null,
    suggestions: [{ subject_id: "s1", name: "LLMs", origin: "shared" }],
  };

  it("returns the suggestions for the document", async () => {
    const { apiClient, fetch } = api(() => json(suggestions));
    await expect(loadSubjectSuggestions("d1", apiClient)).resolves.toEqual(suggestions);
    expect((fetch.mock.calls[0]![0] as Request).url).toBe("http://api.test/documents/d1/subject-suggestions");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadSubjectSuggestions("d1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with the server's detail on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    await expect(loadSubjectSuggestions("d1", apiClient)).rejects.toThrow("Document not found");
  });
});

describe("saveSubjects", () => {
  const choice = { subject_ids: ["s1"], new_names: ["Tool Use"] };

  it("puts the choice and returns the document", async () => {
    const doc = { document_id: "d1", title: "a.pdf", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [] };
    const { apiClient, fetch } = api(() => json(doc));
    await expect(saveSubjects("d1", choice, apiClient)).resolves.toEqual(doc);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("PUT");
    expect(request.url).toBe("http://api.test/documents/d1/subjects");
    expect(await request.json()).toEqual(choice);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(saveSubjects("d1", choice, apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with the server's message on 422", async () => {
    const { apiClient } = api(() => json({ detail: [{ msg: "Choose 1 to 3 subjects" }] }, 422));
    await expect(saveSubjects("d1", choice, apiClient)).rejects.toThrow("Choose 1 to 3 subjects");
  });

  it("rejects with an empty message on a 500 without detail", async () => {
    const { apiClient } = api(() => json({}, 500));
    await expect(saveSubjects("d1", choice, apiClient)).rejects.toThrow(new Error(""));
    await expect(saveSubjects("d1", choice, apiClient)).rejects.toHaveProperty("message", "");
  });

  it("rejects with the server's detail on 409", async () => {
    const { apiClient } = api(() => json({ detail: "Document is not ready for subjects" }, 409));
    await expect(saveSubjects("d1", choice, apiClient)).rejects.toThrow("Document is not ready for subjects");
  });
});

describe("deleteDocument", () => {
  it("sends DELETE to the document's path and resolves on 204", async () => {
    const { apiClient, fetch } = api(() => new Response(null, { status: 204 }));
    await expect(deleteDocument("d3", apiClient)).resolves.toBeUndefined();
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("DELETE");
    expect(request.url).toBe("http://api.test/documents/d3");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(deleteDocument("d3", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with DocumentGoneError on 404 (already deleted)", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    await expect(deleteDocument("d3", apiClient)).rejects.toBeInstanceOf(DocumentGoneError);
  });

  it("rejects with DocumentProcessingError carrying the server's message on 409", async () => {
    const { apiClient } = api(() => json({ detail: "This document is still processing" }, 409));
    const rejection = deleteDocument("d3", apiClient);
    await expect(rejection).rejects.toBeInstanceOf(DocumentProcessingError);
    await expect(rejection).rejects.toThrow("This document is still processing");
  });

  it("rejects with a plain error on other failures", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    const rejection = deleteDocument("d3", apiClient);
    await expect(rejection).rejects.toThrow("boom");
    await expect(rejection).rejects.not.toBeInstanceOf(DocumentGoneError);
    await expect(rejection).rejects.not.toBeInstanceOf(DocumentProcessingError);
  });
});

describe("loadDocumentFile", () => {
  const document = { document_id: "d1", title: "a.pdf", state: "ready", failure_reason: null, created_at: "2026-10-04T09:00:00Z", subjects: [], attempt: null, max_attempts: 3, can_retry: false, authors: [], year: null, archived: false };

  it("returns the link with its expiry computed from now and the document", async () => {
    const { apiClient, fetch } = api(() => json({ url: "http://s3.test/a.pdf?sig=1", expires_in: 300, document }));
    await expect(loadDocumentFile("d1", apiClient, () => 1_000)).resolves.toEqual({ url: "http://s3.test/a.pdf?sig=1", expiresAt: 301_000, document });
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("GET");
    expect(request.url).toBe("http://api.test/documents/d1/file");
  });

  it("rejects with DocumentNotFoundError on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    await expect(loadDocumentFile("d1", apiClient)).rejects.toBeInstanceOf(DocumentNotFoundError);
  });

  it("rejects with DocumentNotOpenableError carrying the detail on 409", async () => {
    const { apiClient } = api(() => json({ detail: "Document is still processing" }, 409));
    const rejection = loadDocumentFile("d1", apiClient);
    await expect(rejection).rejects.toBeInstanceOf(DocumentNotOpenableError);
    await expect(rejection).rejects.toThrow("Document is still processing");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadDocumentFile("d1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain Error on 500", async () => {
    const { apiClient } = api(() => json({ detail: "no" }, 500));
    const rejection = loadDocumentFile("d1", apiClient);
    await expect(rejection).rejects.toThrow("500");
    await expect(rejection).rejects.not.toBeInstanceOf(DocumentNotFoundError);
    await expect(rejection).rejects.not.toBeInstanceOf(DocumentNotOpenableError);
  });
});
