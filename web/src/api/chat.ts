import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { getThread } from "./generated/sdk.gen";
import type {
  AskInNewThreadData,
  AskInNewThreadErrors,
  AskInNewThreadResponses,
  ChooseThreadSubjectsData,
  ChooseThreadSubjectsErrors,
  ChooseThreadSubjectsResponses,
  ThreadResponse,
} from "./generated/types.gen";
import { parseSse } from "./sse";

/** `n` is the number of the answer's inline [n] marker that points at this citation. */
export type ChatCitation = { n: number; chunk_id: string; document_title: string; page: number | null };

type Subject = { subject_id: string; name: string };

/** A thread as GET /threads/{id} shows it; `awaiting_subjects` means its question waits for the learner's pick. */
export type ThreadView = ThreadResponse;

export type ChatEvent =
  | { type: "thread"; thread_id: string; subjects: Subject[] }
  /** Detection was unsure: the thread waits for the learner to pick 1-3 of these subjects. */
  | { type: "choose_subjects"; thread_id: string; question: string; subjects: Subject[] }
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
      return { type: "thread", ...(payload() as { thread_id: string; subjects: Subject[] }) };
    case "choose_subjects":
      return { type: "choose_subjects", ...(payload() as { thread_id: string; question: string; subjects: Subject[] }) };
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
  yield* events(response, "POST /threads");
}

// The learner's pick for a thread waiting for its subjects; the answer to the kept question streams back like
// askInNewThread's (a plain request for the same reasons). A refusal (the pick is invalid, the thread no longer
// waits, it doesn't exist) carries a message for the learner.
export async function* chooseSubjects(
  threadId: string,
  subjectIds: string[],
  apiClient: Client = client,
): AsyncGenerator<ChatEvent> {
  const body: ChooseThreadSubjectsData["body"] = { subject_ids: subjectIds };
  const { error, response } = await apiClient.post<ChooseThreadSubjectsResponses, ChooseThreadSubjectsErrors, false>({
    security: [{ scheme: "bearer", type: "http" }],
    url: "/threads/{thread_id}/subjects",
    path: { thread_id: threadId },
    body,
    headers: { "Content-Type": "application/json" },
    parseAs: "stream",
    throwOnError: false,
  });
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (response && response.status >= 400 && response.status < 500) {
    const message = detail(error);
    if (message === NO_DOCUMENTS) throw new NoDocumentsError(message);
    if (message !== null) throw new AskRefusedError(message);
  }
  yield* events(response, "POST /threads/{thread_id}/subjects");
}

async function* events(response: Response | undefined, request: string): AsyncGenerator<ChatEvent> {
  if (!response?.ok || !response.body) throw new Error(`${request} failed (${response?.status ?? "no response"})`);
  for await (const message of parseSse(response.body)) {
    const event = toEvent(message.event, message.data);
    if (event) yield event;
  }
}

/** The thread for the chat page to resume after a reload; null when it doesn't exist or isn't the learner's. */
export async function loadThread(threadId: string, apiClient: Client = client): Promise<ThreadView | null> {
  const { data, error, response } = await getThread({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (response?.status === 404) return null;
  if (!data) throw new Error(`GET /threads/{thread_id} failed (${response?.status ?? "no response"})`);
  return data;
}

export function formatCitation(c: ChatCitation): string {
  return `${c.document_title}, ${c.page === null ? "page unavailable" : `p. ${c.page}`}`;
}
