import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import {
  askInNewThread,
  AskRefusedError,
  chooseSubjects,
  formatCitation,
  loadThread,
  NoDocumentsError,
  QUESTION_EXPIRED,
  QuestionExpiredError,
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
  'event: thread\ndata: {"thread_id": "t1", "subjects": [{"subject_id": "s1", "name": "General"}]}\n\n',
  'event: delta\ndata: {"text": "It weighs "}\n\n',
  'event: delta\ndata: {"text": "tokens [1]."}\n\n',
  'event: citations\ndata: {"citations": [{"n": 1, "chunk_id": "c1", "document_title": "a.pdf", "page": 3}]}\n\n',
  "event: done\ndata: {}\n\n",
].join("");

describe("askInNewThread", () => {
  it("posts the question with the token and yields the streamed events", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));

    const events = await collect(askInNewThread("What is attention?", apiClient));

    expect(events).toEqual([
      { type: "thread", thread_id: "t1", subjects: [{ subject_id: "s1", name: "General" }] },
      { type: "delta", text: "It weighs " },
      { type: "delta", text: "tokens [1]." },
      { type: "citations", citations: [{ n: 1, chunk_id: "c1", document_title: "a.pdf", page: 3 }] },
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
    const { apiClient } = api(() => json({ detail: "Subject detection isn't available yet" }, 409));
    const failure = collect(askInNewThread("q", apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("Subject detection isn't available yet");
    await expect(failure).rejects.not.toBeInstanceOf(NoDocumentsError);
  });

  it("parses the marker number of each citation", async () => {
    const { apiClient } = api(() =>
      eventStream(
        'event: citations\ndata: {"citations": [{"n": 2, "chunk_id": "c2", "document_title": "b.pdf", "page": null}]}\n\n',
      ),
    );
    expect(await collect(askInNewThread("q", apiClient))).toEqual([
      { type: "citations", citations: [{ n: 2, chunk_id: "c2", document_title: "b.pdf", page: null }] },
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

describe("chooseSubjects", () => {
  it("posts the pick for the waiting thread and yields the answer's events", async () => {
    const { apiClient, fetch } = api(() => eventStream(answer));

    const events = await collect(chooseSubjects("t1", ["s1", "s2"], apiClient));

    expect(events[0]).toEqual({ type: "thread", thread_id: "t1", subjects: [{ subject_id: "s1", name: "General" }] });
    expect(events.at(-1)).toEqual({ type: "done" });
    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.method).toBe("POST");
    expect(request.url).toBe("http://api.test/threads/t1/subjects");
    expect(request.headers.get("Authorization")).toBe("Bearer t");
    expect(await request.json()).toEqual({ subject_ids: ["s1", "s2"] });
  });

  it.each([409, 422])("rejects with AskRefusedError carrying the detail on %i", async (status) => {
    const { apiClient } = api(() => json({ detail: "This conversation already has its subjects." }, status));
    const failure = collect(chooseSubjects("t1", ["s1"], apiClient));
    await expect(failure).rejects.toBeInstanceOf(AskRefusedError);
    await expect(failure).rejects.toThrow("This conversation already has its subjects.");
  });

  it.each([
    ["the tutor no longer holds the question (409)", 409, QUESTION_EXPIRED],
    ["the thread is gone (404)", 404, "No such conversation"],
  ])("rejects with QuestionExpiredError when %s", async (_, status, message) => {
    const { apiClient } = api(() => json({ detail: message }, status));
    const failure = collect(chooseSubjects("t1", ["s1"], apiClient));
    await expect(failure).rejects.toBeInstanceOf(QuestionExpiredError);
    await expect(failure).rejects.toThrow(QUESTION_EXPIRED);
  });

  it("rejects with NoDocumentsError when the learner has no ready documents", async () => {
    const { apiClient } = api(() => json({ detail: "Upload a document first" }, 409));
    await expect(collect(chooseSubjects("t1", ["s1"], apiClient))).rejects.toBeInstanceOf(NoDocumentsError);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(collect(chooseSubjects("t1", ["s1"], apiClient))).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects with a plain Error on 503", async () => {
    const { apiClient } = api(() => json({ detail: "unavailable" }, 503));
    const failure = collect(chooseSubjects("t1", ["s1"], apiClient));
    await expect(failure).rejects.toThrow("503");
    await expect(failure).rejects.not.toBeInstanceOf(AskRefusedError);
  });
});

describe("choose_subjects event", () => {
  it("carries the question waiting for the learner's pick", async () => {
    const { apiClient } = api(() =>
      eventStream(
        'event: choose_subjects\ndata: {"thread_id": "t1", "question": "How?", "subjects": [{"subject_id": "s1", "name": "LLMs"}]}\n\n' +
          "event: done\ndata: {}\n\n",
      ),
    );
    expect(await collect(askInNewThread("How?", apiClient))).toEqual([
      { type: "choose_subjects", thread_id: "t1", question: "How?", subjects: [{ subject_id: "s1", name: "LLMs" }] },
      { type: "done" },
    ]);
  });
});

describe("loadThread", () => {
  it("returns the thread", async () => {
    const view = { thread_id: "t1", question: "How?", subjects: [], awaiting_subjects: true };
    const { apiClient, fetch } = api(() => json(view));
    expect(await loadThread("t1", apiClient)).toEqual(view);
    expect((fetch.mock.calls[0]![0] as Request).url).toBe("http://api.test/threads/t1");
  });

  it("returns null when there is no such thread", async () => {
    const { apiClient } = api(() => json({ detail: "Not found" }, 404));
    expect(await loadThread("t1", apiClient)).toBeNull();
  });

  it("returns null when the id is not a thread id (422)", async () => {
    const { apiClient } = api(() => json({ detail: [{ msg: "Input should be a valid UUID" }] }, 422));
    expect(await loadThread("nope", apiClient)).toBeNull();
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadThread("t1", apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });

  it("rejects on a server error", async () => {
    const { apiClient } = api(() => json({ detail: "boom" }, 500));
    await expect(loadThread("t1", apiClient)).rejects.toThrow("500");
  });
});

describe("formatCitation", () => {
  it("shows the title and page, or says the page is unavailable", () => {
    expect(formatCitation({ n: 1, chunk_id: "c1", document_title: "a.pdf", page: 3 })).toBe("a.pdf, p. 3");
    expect(formatCitation({ n: 1, chunk_id: "c2", document_title: "a.pdf", page: null })).toBe("a.pdf, page unavailable");
  });
});
