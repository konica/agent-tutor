import { SessionExpiredError } from "../auth/authClient";
import { failure, sessionOver } from "./documents";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listMySubjects, searchSubjects } from "./generated/sdk.gen";
import type { SubjectMatchResponse, SubjectResponse } from "./generated/types.gen";

export type SubjectMatch = SubjectMatchResponse;

// The subjects of the learner's ready documents, named for them, sorted by name.
export async function loadMySubjects(apiClient: Client = client): Promise<SubjectResponse[]> {
  const { data, error, response } = await listMySubjects({ client: apiClient, throwOnError: false });
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /me/subjects failed (${response?.status ?? "no response"})`);
  return data;
}

// The shared catalog for the picker's type-ahead: the learner's subjects first (PRD §8 US-2b).
export async function searchCatalog(query: string, apiClient: Client = client): Promise<SubjectMatch[]> {
  const { data, error, response } = await searchSubjects({ client: apiClient, query: { q: query }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}
