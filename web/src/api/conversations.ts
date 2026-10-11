import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { archiveThread, listThreads, restoreThread } from "./generated/sdk.gen";
import type { ThreadResponse, ThreadSummaryResponse } from "./generated/types.gen";
import { sessionOver } from "./documents";

export type { ThreadResponse, ThreadSummaryResponse };

// The learner's active conversations, or archived ones, newest last activity first (owner only).
export async function listConversations({ archived = false }: { archived?: boolean } = {}, apiClient: Client = client): Promise<ThreadSummaryResponse[]> {
  const { data, error, response } = await listThreads({ client: apiClient, query: archived ? { archived: true } : undefined, throwOnError: false });
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
