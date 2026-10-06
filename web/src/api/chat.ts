import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import type { AskInNewThreadData, AskInNewThreadErrors, AskInNewThreadResponses } from "./generated/types.gen";
import { parseSse } from "./sse";

/** `n` is the number of the answer's inline [n] marker that points at this citation. */
export type ChatCitation = { n: number; chunk_id: string; document_title: string; page: number | null };

export type ChatEvent =
  | { type: "thread"; thread_id: string; subjects: { subject_id: string; name: string }[] }
  | { type: "delta"; text: string }
  | { type: "citations"; citations: ChatCitation[] }
  | { type: "error"; code: "unauthenticated" | "unavailable"; message: string }
  | { type: "done" };

export const NO_DOCUMENTS = "Upload a document first";

/** 409 from POST /threads: the learner has no ready documents yet. */
export class NoDocumentsError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NoDocumentsError";
  }
}

/** Another 409 from POST /threads (e.g. subject detection isn't available yet): its message is for the learner. */
export class AskRefusedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AskRefusedError";
  }
}

function detail(error: unknown): string | null {
  if (typeof error === "object" && error !== null && "detail" in error && typeof error.detail === "string") return error.detail;
  return null;
}

// Data is parsed only for known events: an unknown event is skipped whatever its data looks like.
function toEvent(event: string, data: string): ChatEvent | null {
  const payload = () => JSON.parse(data) as Record<string, unknown>;
  switch (event) {
    case "thread":
      return { type: "thread", ...(payload() as { thread_id: string; subjects: { subject_id: string; name: string }[] }) };
    case "delta":
      return { type: "delta", text: payload().text as string };
    case "citations":
      return { type: "citations", citations: payload().citations as ChatCitation[] };
    case "error":
      return { type: "error", ...(payload() as { code: "unauthenticated" | "unavailable"; message: string }) };
    case "done":
      return { type: "done" };
    default:
      return null; // an event this client doesn't know yet
  }
}

// POST /threads streams the answer as server-sent events. This is a plain request through the configured
// client, not the generated SSE helper: the helper skips response interceptors (so a 401 would not end the
// session) and retries failed connections, which would post the question again and start another thread.
export async function* askInNewThread(question: string, apiClient: Client = client): AsyncGenerator<ChatEvent> {
  const body: AskInNewThreadData["body"] = { question };
  const { error, response } = await apiClient.post<AskInNewThreadResponses, AskInNewThreadErrors, false>({
    security: [{ scheme: "bearer", type: "http" }],
    url: "/threads",
    body,
    headers: { "Content-Type": "application/json" },
    parseAs: "stream",
    throwOnError: false,
  });
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (response?.status === 409) {
    const message = detail(error);
    if (message === NO_DOCUMENTS) throw new NoDocumentsError(message);
    if (message !== null) throw new AskRefusedError(message);
  }
  if (!response?.ok || !response.body) throw new Error(`POST /threads failed (${response?.status ?? "no response"})`);
  for await (const message of parseSse(response.body)) {
    const event = toEvent(message.event, message.data);
    if (event) yield event;
  }
}

export function formatCitation(c: ChatCitation): string {
  return `${c.document_title}, ${c.page === null ? "page unavailable" : `p. ${c.page}`}`;
}
