import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import {
  addThreadDocuments,
  askInNewThread,
  askInThread,
  AskRefusedError,
  ConversationNotFoundError,
  formatCitation,
  loadConversation,
  loadDocumentsUsed,
  rateAnswer,
  removeThreadDocument,
  renameConversation,
  setSearchScope,
  type ChatEvent,
} from "./chat";
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
  'event: thread\ndata: {"thread_id": "t1", "run_id": "r1"}\n\n',
  'event: delta\ndata: {"text": "It weighs "}\n\n',
  'event: delta\ndata: {"text": "tokens [1]."}\n\n',
  'event: citations\ndata: {"citations": [{"n": 1, "chunk_id": "c1", "document_id": "d1", "document_title": "a.pdf", "page": 3}]}\n\n',
  "event: done\ndata: {}\n\n",
].join("");

describe("askInNewThread", () => {
  it("posts the question with the token and yields the streamed events", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));

    const events = await collect(askInNewThread("What is attention?", undefined, apiClient));

    expect(events).toEqual([
      { type: "thread", thread_id: "t1", run_id: "r1" },
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

  it("sends the starting document with the question when given one", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));
    await collect(askInNewThread("What is attention?", "d1", apiClient));
    const request = fetch.mock.calls[0]![0] as Request;
    expect(await request.json()).toEqual({ question: "What is attention?", document_id: "d1" });
  });

  it("sends no document_id key without a starting document", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));
    await collect(askInNewThread("q", undefined, apiClient));
    const body = (await (fetch.mock.calls[0]![0] as Request).json()) as Record<string, unknown>;
    expect("document_id" in body).toBe(false);
  });

  it("rejects with AskRefusedError carrying the detail on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    const failure = collect(askInNewThread("q", "d9", apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("Document not found");
  });

  it("rejects with AskRefusedError and a fallback message on a 404 without detail", async () => {
    const { apiClient } = api(() => json({}, 404));
    const failure = collect(askInNewThread("q", "d9", apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("That document can't be used. Start a new conversation.");
  });

  it("yields an error event that ends the stream", async () => {
    const { apiClient } = api(() =>
      eventStream('event: error\ndata: {"code": "unauthenticated", "message": "Please sign in again."}\n\n'),
    );
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([
      { type: "error", code: "unauthenticated", message: "Please sign in again." },
    ]);
  });

  it("rejects with SessionExpiredError on 401 and reports it", async () => {
    const { apiClient, onUnauthorized } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(collect(askInNewThread("q", undefined, apiClient))).rejects.toBeInstanceOf(SessionExpiredError);
    expect(onUnauthorized).toHaveBeenCalled();
  });

  it("rejects with AskRefusedError carrying the detail on any other 409", async () => {
    const { apiClient } = api(() => json({ detail: "The tutor can't answer that right now" }, 409));
    const failure = collect(askInNewThread("q", undefined, apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("The tutor can't answer that right now");
  });

  it("reads a no_documents decline", async () => {
    const { apiClient } = api(() =>
      eventStream(
        'event: decline\ndata: {"code": "no_documents", "message": "None of your documents can be used right now: they are all archived or deleted."}\n\n' +
          "event: done\ndata: {}\n\n",
      ),
    );
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([
      { type: "decline", code: "no_documents", message: "None of your documents can be used right now: they are all archived or deleted." },
      { type: "done" },
    ]);
  });

  it("parses the marker number of each citation", async () => {
    const { apiClient } = api(() =>
      eventStream(
        'event: citations\ndata: {"citations": [{"n": 2, "chunk_id": "c2", "document_id": "d2", "document_title": "b.pdf", "page": null}]}\n\n',
      ),
    );
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([
      { type: "citations", citations: [{ n: 2, chunk_id: "c2", document_id: "d2", document_title: "b.pdf", page: null }] },
    ]);
  });

  it("skips an unknown event even when its data is not JSON", async () => {
    const { apiClient } = api(() => eventStream('event: ping\ndata: ok\n\nevent: delta\ndata: {"text": "Hi"}\n\n'));
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([{ type: "delta", text: "Hi" }]);
  });

  it("rejects with a plain Error on 503", async () => {
    const { apiClient } = api(() => json({ detail: "The tutor is unavailable. Try again in a moment." }, 503));
    const failure = collect(askInNewThread("q", undefined, apiClient));
    await expect(failure).rejects.toThrow("503");
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
    { document_id: "d2", title: "RAG", authors: [], year: null, archived: true, deleted: false, added_by: "answer", used: true },
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

describe("addThreadDocuments", () => {
  const list = [
    { document_id: "d1", title: "ReAct", authors: ["Yao"], year: 2023, archived: false, deleted: false, added_by: "answer", used: true },
    { document_id: "d2", title: "RAG", authors: [], year: null, archived: false, deleted: false, added_by: "learner", used: false },
  ];

  it("posts the document ids with the token and returns the full list", async () => {
    const { apiClient, fetch } = api(() => json(list));
    expect(await addThreadDocuments("t1", ["d2"], apiClient)).toEqual(list);
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("http://api.test/threads/t1/documents");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ document_ids: ["d2"] });
  });

  it("rejects with SessionExpiredError on 401 and reports it", async () => {
    const { apiClient, onUnauthorized } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(addThreadDocuments("t1", ["d2"], apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
    expect(onUnauthorized).toHaveBeenCalled();
  });

  it("rejects with a plain Error on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Document not found" }, 404));
    const failure = addThreadDocuments("t1", ["d2"], apiClient);
    await expect(failure).rejects.toThrow("404");
    await expect(failure).rejects.not.toBeInstanceOf(SessionExpiredError);
  });
});

describe("removeThreadDocument", () => {
  it("deletes the document from the thread's list with the token", async () => {
    const { apiClient, fetch } = api(() => new Response(null, { status: 204 }));
    await expect(removeThreadDocument("t1", "d1", apiClient)).resolves.toBeUndefined();
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("DELETE");
    expect(request.url).toBe("http://api.test/threads/t1/documents/d1");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(removeThreadDocument("t1", "d1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain Error on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Conversation not found" }, 404));
    const failure = removeThreadDocument("t1", "d1", apiClient);
    await expect(failure).rejects.toThrow("404");
    await expect(failure).rejects.not.toBeInstanceOf(SessionExpiredError);
  });
});

describe("renameConversation", () => {
  it("patches the thread's title with the token and returns the saved title", async () => {
    const { apiClient, fetch } = api(() => json({ thread_id: "t1", title: "Attention basics" }));
    expect(await renameConversation("t1", " Attention basics ", apiClient)).toBe("Attention basics");
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("PATCH");
    expect(request.url).toBe("http://api.test/threads/t1");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ title: " Attention basics " });
  });

  it("rejects with the server's message when the title is refused", async () => {
    const { apiClient } = api(() => json({ detail: "Use at most 120 characters" }, 422));
    await expect(renameConversation("t1", "x".repeat(121), apiClient)).rejects.toThrow("Use at most 120 characters");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(renameConversation("t1", "New", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});

describe("askInThread", () => {
  it("posts the question to the conversation and yields its events, a decline included", async () => {
    const { apiClient, fetch } = api(() =>
      eventStream(
        [
          'event: thread\ndata: {"thread_id": "t1"}\n\n',
          'event: decline\ndata: {"code": "limited", "message": "These documents don\'t cover this."}\n\n',
          "event: done\ndata: {}\n\n",
        ].join(""),
      ),
    );

    const events = await collect(askInThread("t1", "Why?", apiClient));

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("http://api.test/threads/t1/questions");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ question: "Why?" });
    expect(events).toEqual([
      { type: "thread", thread_id: "t1", run_id: null },
      { type: "decline", code: "limited", message: "These documents don't cover this." },
      { type: "done" },
    ]);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(collect(askInThread("t1", "q", apiClient))).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with AskRefusedError carrying the detail on 409", async () => {
    const { apiClient } = api(() => json({ detail: "Add documents to limit the search." }, 409));
    const failure = collect(askInThread("t1", "q", apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("Add documents to limit the search.");
  });

  it("rejects with a plain Error on 503", async () => {
    const { apiClient } = api(() => json({ detail: "unavailable" }, 503));
    await expect(collect(askInThread("t1", "q", apiClient))).rejects.toThrow("503");
  });
});

describe("setSearchScope", () => {
  it("patches the scope and resolves with the saved one", async () => {
    const { apiClient, fetch } = api(() => json({ thread_id: "t1", title: "q", search_scope: "listed" }));
    await expect(setSearchScope("t1", "listed", apiClient)).resolves.toBe("listed");
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("PATCH");
    expect(request.url).toBe("http://api.test/threads/t1");
    expect(await request.json()).toEqual({ search_scope: "listed" });
  });

  it("rejects with the server's message when refused", async () => {
    const { apiClient } = api(() => json({ detail: "Add documents to limit the search." }, 409));
    await expect(setSearchScope("t1", "listed", apiClient)).rejects.toThrow("Add documents to limit the search.");
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(setSearchScope("t1", "library", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});

describe("loadConversation", () => {
  const thread = { thread_id: "t1", title: "Attention basics", search_scope: "listed" };
  const turns = [
    {
      question: "What is attention?",
      answer: "It weighs tokens [1].",
      citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3, archived: false, deleted: false }],
      decline: null,
      created_at: "2026-10-10T09:00:00Z",
    },
  ];
  // GET /threads/t1 answers with `thread`, GET /threads/t1/turns with `turnsResponse`.
  const routes = (threadResponse: () => Response, turnsResponse: () => Response) => (request: Request) =>
    new URL(request.url).pathname.endsWith("/turns") ? turnsResponse() : threadResponse();

  it("gets the thread and its turns with the token", async () => {
    const { apiClient, fetch } = api(routes(() => json(thread), () => json(turns)));
    expect(await loadConversation("t1", apiClient)).toEqual({ thread, turns });
    const requests = fetch.mock.calls.map(([r]) => r as Request);
    expect(requests.map((r) => `${r.method} ${r.url}`).sort()).toEqual([
      "GET http://api.test/threads/t1",
      "GET http://api.test/threads/t1/turns",
    ]);
    for (const r of requests) expect(r.headers.get("Authorization")).toBe("Bearer t");
  });

  it.each([
    ["the thread", () => json({ detail: "Conversation not found" }, 404), () => json(turns)],
    ["its turns", () => json(thread), () => json({ detail: "Conversation not found" }, 404)],
  ])("rejects with ConversationNotFoundError when %s is a 404", async (_, threadResponse, turnsResponse) => {
    const { apiClient } = api(routes(threadResponse, turnsResponse));
    await expect(loadConversation("t1", apiClient)).rejects.toBeInstanceOf(ConversationNotFoundError);
  });

  it("rejects with ConversationNotFoundError on 422 (not a conversation id)", async () => {
    const { apiClient } = api(() => json({ detail: [{ msg: "Input should be a valid UUID" }] }, 422));
    await expect(loadConversation("nope", apiClient)).rejects.toBeInstanceOf(ConversationNotFoundError);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadConversation("t1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain Error on 500", async () => {
    const { apiClient } = api(routes(() => json(thread), () => json({ detail: "boom" }, 500)));
    const failure = loadConversation("t1", apiClient);
    await expect(failure).rejects.toThrow("500");
    await expect(failure).rejects.not.toBeInstanceOf(ConversationNotFoundError);
    await expect(failure).rejects.not.toBeInstanceOf(SessionExpiredError);
  });
});

describe("rateAnswer", () => {
  it("puts the rating on the turn with the token and returns the saved rating", async () => {
    const { apiClient, fetch } = api(() => json({ rating: "down" }));

    expect(await rateAnswer("t1", "r1", "down", apiClient)).toBe("down");

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("PUT");
    expect(request.url).toBe("http://api.test/threads/t1/turns/r1/rating");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ rating: "down" });
  });

  it("rejects with an Error on 404", async () => {
    const { apiClient } = api(() => json({ detail: "Not found" }, 404));
    await expect(rateAnswer("t1", "r1", "up", apiClient)).rejects.toThrow(/failed \(404\)/);
  });

  it("rejects with SessionExpiredError on 401 and reports it", async () => {
    const { apiClient, onUnauthorized } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(rateAnswer("t1", "r1", "up", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
    expect(onUnauthorized).toHaveBeenCalled();
  });
});
