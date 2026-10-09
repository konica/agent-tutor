import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import {
  addThreadDocuments as addThreadDocumentsSdk,
  listThreadDocuments,
  removeThreadDocument as removeThreadDocumentSdk,
  updateThread,
} from "./generated/sdk.gen";
import type {
  AskInNewThreadData,
  AskInNewThreadErrors,
  AskInNewThreadResponses,
  AskInThreadData,
  AskInThreadErrors,
  AskInThreadResponses,
  ThreadDocumentResponse,
} from "./generated/types.gen";
import { failure, sessionOver } from "./documents";
import { parseSse } from "./sse";

export type { ThreadDocumentResponse };

/** `n` is the number of the answer's inline [n] marker that points at this citation. */
export type ChatCitation = { n: number; chunk_id: string; document_id: string; document_title: string; page: number | null };

export type ChatEvent =
  | { type: "thread"; thread_id: string }
  | { type: "delta"; text: string }
  | { type: "citations"; citations: ChatCitation[] }
  | { type: "decline"; code: "limited"; message: string }
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

/** Another 409 from POST /threads: its message is for the learner. */
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
      return { type: "thread", thread_id: payload().thread_id as string };
    case "delta":
      return { type: "delta", text: payload().text as string };
    case "citations":
      return { type: "citations", citations: payload().citations as ChatCitation[] };
    case "decline":
      return { type: "decline", ...(payload() as { code: "limited"; message: string }) };
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
export function askInNewThread(question: string, apiClient: Client = client): AsyncGenerator<ChatEvent> {
  return stream("/threads", question, apiClient);
}

// POST /threads/{id}/questions: the same stream for a question in an existing conversation.
export function askInThread(threadId: string, question: string, apiClient: Client = client): AsyncGenerator<ChatEvent> {
  return stream(`/threads/${encodeURIComponent(threadId)}/questions`, question, apiClient);
}

async function* stream(url: string, question: string, apiClient: Client): AsyncGenerator<ChatEvent> {
  const body: AskInNewThreadData["body"] & AskInThreadData["body"] = { question };
  const { error, response } = await apiClient.post<AskInNewThreadResponses & AskInThreadResponses, AskInNewThreadErrors & AskInThreadErrors, false>({
    security: [{ scheme: "bearer", type: "http" }],
    url,
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
  if (!response?.ok || !response.body) throw new Error(`POST ${url} failed (${response?.status ?? "no response"})`);
  for await (const message of parseSse(response.body)) {
    const event = toEvent(message.event, message.data);
    if (event) yield event;
  }
}

// The documents a conversation's answers drew on, in the API's order (owner only; another learner's thread is a 404).
export async function loadDocumentsUsed(threadId: string, apiClient: Client = client): Promise<ThreadDocumentResponse[]> {
  const { data, error, response } = await listThreadDocuments({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /threads/${threadId}/documents failed (${response?.status ?? "no response"})`);
  return data;
}

// Adds the learner's ready documents to the conversation's list and returns the full list. All or nothing: a document
// that isn't the learner's ready, non-archived one, or another learner's thread, is a 404 and nothing is added.
export async function addThreadDocuments(threadId: string, documentIds: string[], apiClient: Client = client): Promise<ThreadDocumentResponse[]> {
  const { data, error, response } = await addThreadDocumentsSdk({
    client: apiClient,
    path: { thread_id: threadId },
    body: { document_ids: documentIds },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /threads/${threadId}/documents failed (${response?.status ?? "no response"})`);
  return data;
}

// Takes a document off the conversation's list; the document and earlier answers stay as they are. Not listed is fine (204).
export async function removeThreadDocument(threadId: string, documentId: string, apiClient: Client = client): Promise<void> {
  const { error, response } = await removeThreadDocumentSdk({
    client: apiClient,
    path: { thread_id: threadId, document_id: documentId },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!response?.ok) throw new Error(`DELETE /threads/${threadId}/documents/${documentId} failed (${response?.status ?? "no response"})`);
}

// Renames the learner's conversation and returns the saved (trimmed) title. A refusal (empty, over 120 characters,
// archived, not theirs) rejects with the server's message, or an empty one when it gave none.
export async function renameConversation(threadId: string, title: string, apiClient: Client = client): Promise<string> {
  const { data, error, response } = await updateThread({
    client: apiClient,
    path: { thread_id: threadId },
    body: { title },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data.title ?? title.trim();
}

export type SearchScope = "library" | "listed";

// Limits the conversation's search to its listed documents ("listed") or opens it to the whole library ("library") and
// returns the saved scope. A refusal (409 when limiting an empty list, not theirs) rejects with the server's message.
export async function setSearchScope(threadId: string, scope: SearchScope, apiClient: Client = client): Promise<SearchScope> {
  const { data, error, response } = await updateThread({
    client: apiClient,
    path: { thread_id: threadId },
    body: { search_scope: scope },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data.search_scope;
}

export function formatCitation(c: ChatCitation): string {
  return `${c.document_title}, ${c.page === null ? "page unavailable" : `p. ${c.page}`}`;
}
