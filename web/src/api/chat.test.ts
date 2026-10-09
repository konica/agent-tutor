import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { askInNewThread, AskRefusedError, formatCitation, loadDocumentsUsed, NoDocumentsError, type ChatEvent } from "./chat";
import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";

function api(handler: (request: Request) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const onUnauthorized = vi.fn();
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized, apiClient });
  return { apiClient, fetch, onUnauthorized };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function eventStream(text: string): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(text));
      controller.close();
    },
  });
  return new Response(stream, { headers: { "Content-Type": "text/event-stream" } });
}

async function collect(events: AsyncIterable<ChatEvent>): Promise<ChatEvent[]> {
  const list: ChatEvent[] = [];
  for await (const event of events) list.push(event);
  return list;
}

const answer = [
  'event: thread\ndata: {"thread_id": "t1"}\n\n',
  'event: delta\ndata: {"text": "It weighs "}\n\n',
  'event: delta\ndata: {"text": "tokens [1]."}\n\n',
  'event: citations\ndata: {"citations": [{"n": 1, "chunk_id": "c1", "document_id": "d1", "document_title": "a.pdf", "page": 3}]}\n\n',
  "event: done\ndata: {}\n\n",
].join("");

describe("askInNewThread", () => {
  it("posts the question with the token and yields the streamed events", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));

    const events = await collect(askInNewThread("What is attention?", apiClient));

    expect(events).toEqual([
      { type: "thread", thread_id: "t1" },
      { type: "delta", text: "It weighs " },
      { type: "delta", text: "tokens [1]." },
      { type: "citations", citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3 }] },
      { type: "done" },
    ]);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("http://api.test/threads");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ question: "What is attention?" });
  });

  it("yields an error event that ends the stream", async () => {
    const { apiClient } = api(() =>
      eventStream('event: error\ndata: {"code": "unauthenticated", "message": "Please sign in again."}\n\n'),
    );
    expect(await collect(askInNewThread("q", apiClient))).toEqual([
      { type: "error", code: "unauthenticated", message: "Please sign in again." },
    ]);
  });

  it("rejects with SessionExpiredError on 401 and reports it", async () => {
    const { apiClient, onUnauthorized } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(collect(askInNewThread("q", apiClient))).rejects.toBeInstanceOf(SessionExpiredError);
    expect(onUnauthorized).toHaveBeenCalled();
  });

  it("rejects with NoDocumentsError carrying the API's message on 409", async () => {
    const { apiClient } = api(() => json({ detail: "Upload a document first" }, 409));
    const failure = collect(askInNewThread("q", apiClient));
    await expect(failure).rejects.toBeInstanceOf(NoDocumentsError);
    await expect(failure).rejects.toThrow("Upload a document first");
  });

  it("rejects with AskRefusedError carrying the detail on any other 409", async () => {
    const { apiClient } = api(() => json({ detail: "The tutor can't answer that right now" }, 409));
    const failure = collect(askInNewThread("q", apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("The tutor can't answer that right now");
    await expect(failure).rejects.not.toBeInstanceOf(NoDocumentsError);
  });

  it("parses the marker number of each citation", async () => {
    const { apiClient } = api(() =>
      eventStream(
        'event: citations\ndata: {"citations": [{"n": 2, "chunk_id": "c2", "document_id": "d2", "document_title": "b.pdf", "page": null}]}\n\n',
      ),
    );
    expect(await collect(askInNewThread("q", apiClient))).toEqual([
      { type: "citations", citations: [{ n: 2, chunk_id: "c2", document_id: "d2", document_title: "b.pdf", page: null }] },
    ]);
  });

  it("skips an unknown event even when its data is not JSON", async () => {
    const { apiClient } = api(() => eventStream('event: ping\ndata: ok\n\nevent: delta\ndata: {"text": "Hi"}\n\n'));
    expect(await collect(askInNewThread("q", apiClient))).toEqual([{ type: "delta", text: "Hi" }]);
  });

  it("rejects with a plain Error on 503", async () => {
    const { apiClient } = api(() => json({ detail: "The tutor is unavailable. Try again in a moment." }, 503));
    const failure = collect(askInNewThread("q", apiClient));
    await expect(failure).rejects.toThrow("503");
    await expect(failure).rejects.not.toBeInstanceOf(NoDocumentsError);
  });
});

describe("formatCitation", () => {
  it("shows the title and page, or says the page is unavailable", () => {
    expect(formatCitation({ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3 })).toBe("a.pdf, p. 3");
    expect(formatCitation({ n: 1, chunk_id: "c2", document_id: "d1", document_title: "a.pdf", page: null })).toBe("a.pdf, page unavailable");
  });
});

describe("loadDocumentsUsed", () => {
  const used = [
    { document_id: "d1", title: "ReAct", authors: ["Yao"], year: 2023, archived: false, deleted: false, added_by: "answer", used: true },
    { document_id: "d2", title: "RAG", authors: [], year: null, archived: true, deleted: false },
  ];

  it("gets the thread's documents used with the token", async () => {
    const { apiClient, fetch } = api(() => json(used));
    expect(await loadDocumentsUsed("t1", apiClient)).toEqual(used);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("GET");
    expect(request.url).toBe("http://api.test/threads/t1/documents");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadDocumentsUsed("t1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain Error on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Not found" }, 404));
    const failure = loadDocumentsUsed("t1", apiClient);
    await expect(failure).rejects.toThrow("404");
    await expect(failure).rejects.not.toBeInstanceOf(SessionExpiredError);
  });
});
