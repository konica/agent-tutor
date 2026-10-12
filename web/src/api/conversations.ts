import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { archiveThread, listThreads, restoreThread } from "./generated/sdk.gen";
import type { ThreadResponse, ThreadSummaryResponse } from "./generated/types.gen";
import { sessionOver } from "./documents";

export type { ThreadResponse, ThreadSummaryResponse };

// What the Conversations list narrows by (PRD US-13); every field is optional and they combine. Dates are YYYY-MM-DD
// calendar days of last activity; `q` searches titles only.
export type ConversationFilters = { subject_id?: string; active_from?: string; active_to?: string; q?: string };

// A blank search is not a filter.
export const hasConversationFilters = (f: ConversationFilters) => Boolean(f.subject_id || f.active_from || f.active_to || f.q?.trim());

// The learner's active conversations, or with `archived` the archived ones, newest last activity first (owner only),
// narrowed by the filters.
export async function listConversations(
  { archived = false, ...filters }: ConversationFilters & { archived?: boolean } = {},
  apiClient: Client = client,
): Promise<ThreadSummaryResponse[]> {
  const q = filters.q?.trim();
  const query = {
    ...(archived ? { archived: true } : {}),
    ...(filters.subject_id ? { subject_id: [filters.subject_id] } : {}),
    ...(filters.active_from ? { active_from: filters.active_from } : {}),
    ...(filters.active_to ? { active_to: filters.active_to } : {}),
    ...(q ? { q } : {}),
  };
  const { data, error, response } = await listThreads({ client: apiClient, query, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /threads failed (${response?.status ?? "no response"})`);
  return data;
}

// Archive or restore the learner's conversation (US-13); repeating either is harmless.
export async function archiveConversation(threadId: string, apiClient: Client = client): Promise<ThreadResponse> {
  const { data, error, response } = await archiveThread({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`Archiving failed (${response?.status ?? "no response"})`);
  return data;
}

export async function restoreConversation(threadId: string, apiClient: Client = client): Promise<ThreadResponse> {
  const { data, error, response } = await restoreThread({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`Restoring failed (${response?.status ?? "no response"})`);
  return data;
}
