import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import {
  addThreadDocuments as addThreadDocumentsSdk,
  getThread,
  listThreadDocuments,
  listThreadTurns,
  rateTurn,
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
  ThreadResponse,
  TurnResponse,
} from "./generated/types.gen";
import { failure, sessionOver } from "./documents";
import { parseSse } from "./sse";

export type { ThreadDocumentResponse, ThreadResponse, TurnResponse };
export type Conversation = { thread: ThreadResponse; turns: TurnResponse[] };

/** `n` is the number of the answer's inline [n] marker that points at this citation. `archived` and `deleted` come
 * only with a conversation's history; a live answer's citation has neither. */
export type ChatCitation = {
  n: number;
  chunk_id: string;
  document_id: string;
  document_title: string;
  page: number | null;
  archived?: boolean;
  deleted?: boolean;
};

export type Rating = "up" | "down";

export type DeclineCode = "limited" | "no_documents" | "guard" | "off_topic";

export type ChatEvent =
  | { type: "thread"; thread_id: string; run_id: string | null }
  | { type: "delta"; text: string }
  | { type: "citations"; citations: ChatCitation[] }
  | { type: "decline"; code: DeclineCode; message: string }
  // A guard tripped: show `text` in place of the partial answer; nothing else follows but done.
  | { type: "replace"; code: string; text: string }
  | { type: "error"; code: "unauthenticated" | "unavailable"; message: string }
  | { type: "done" };

const DOCUMENT_UNUSABLE = "That document can't be used. Start a new conversation.";

/** 404 (unknown, or another learner's) or 422 (not a conversation id) from a conversation's URL. */
export class ConversationNotFoundError extends Error {
  constructor() {
    super("Conversation not found");
    this.name = "ConversationNotFoundError";
  }
}

/** A 409 from an ask (e.g. an archived conversation), or a 404 for a starting document the learner can't use: its message is for the learner. */
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
    case "thread": {
      const p = payload();
      return { type: "thread", thread_id: p.thread_id as string, run_id: (p.run_id as string | undefined) ?? null };
    }
    case "delta":
      return { type: "delta", text: payload().text as string };
    case "citations":
      return { type: "citations", citations: payload().citations as ChatCitation[] };
    case "decline":
      return { type: "decline", ...(payload() as { code: DeclineCode; message: string }) };
    case "replace":
      return { type: "replace", ...(payload() as { code: string; text: string }) };
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
// `documentId` is the document the conversation starts from (listed first in its documents); a 404 means it isn't
// the learner's ready, non-archived document, and nothing was started.
export function askInNewThread(question: string, documentId?: string, apiClient: Client = client): AsyncGenerator<ChatEvent> {
  const body: AskInNewThreadData["body"] = documentId === undefined ? { question } : { question, document_id: documentId };
  return stream("/threads", body, apiClient, DOCUMENT_UNUSABLE);
}

// POST /threads/{id}/questions: the same stream for a question in an existing conversation.
export function askInThread(threadId: string, question: string, apiClient: Client = client): AsyncGenerator<ChatEvent> {
  const body: AskInThreadData["body"] = { question };
  return stream(`/threads/${encodeURIComponent(threadId)}/questions`, body, apiClient);
}

// `notFound` is the message for a 404 the server gave no detail for; without it a 404 is a plain failure.
async function* stream(
  url: string,
  body: AskInNewThreadData["body"] | AskInThreadData["body"],
  apiClient: Client,
  notFound?: string,
): AsyncGenerator<ChatEvent> {
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
    if (message !== null) throw new AskRefusedError(message);
  }
  if (response?.status === 404 && notFound !== undefined) throw new AskRefusedError(detail(error) ?? notFound);
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

// A conversation at its URL: its title and scope, and its turns oldest first (owner only).
export async function loadConversation(threadId: string, apiClient: Client = client): Promise<Conversation> {
  const path = { thread_id: threadId };
  const [thread, turns] = await Promise.all([
    getThread({ client: apiClient, path, throwOnError: false }),
    listThreadTurns({ client: apiClient, path, throwOnError: false }),
  ]);
  for (const { error, response } of [thread, turns]) {
    if (sessionOver(error, response)) throw new SessionExpiredError();
    if (response?.status === 404 || response?.status === 422) throw new ConversationNotFoundError();
  }
  if (!thread.data || !turns.data) {
    const status = (thread.data ? turns : thread).response?.status ?? "no response";
    throw new Error(`GET /threads/${threadId} failed (${status})`);
  }
  return { thread: thread.data, turns: turns.data };
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

// Rates a kept answer or decline of the learner's conversation; a new rating replaces the last (PRD §10.2). Another
// learner's conversation, or an answer that wasn't kept, is a 404.
export async function rateAnswer(threadId: string, runId: string, rating: Rating, apiClient: Client = client): Promise<Rating> {
  const { data, error, response } = await rateTurn({
    client: apiClient,
    path: { thread_id: threadId, run_id: runId },
    body: { rating },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`PUT /threads/${threadId}/turns/${runId}/rating failed (${response?.status ?? "no response"})`);
  return data.rating;
}
