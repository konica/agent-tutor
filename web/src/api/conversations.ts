import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listThreads } from "./generated/sdk.gen";
import type { ThreadSummaryResponse } from "./generated/types.gen";
import { sessionOver } from "./documents";

export type { ThreadSummaryResponse };

// The learner's active conversations, newest last activity first (owner only).
export async function listConversations(apiClient: Client = client): Promise<ThreadSummaryResponse[]> {
  const { data, error, response } = await listThreads({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /threads failed (${response?.status ?? "no response"})`);
  return data;
}
