import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listMySubjects } from "./generated/sdk.gen";
import type { SubjectResponse } from "./generated/types.gen";

// The subjects of the learner's ready documents, named for them, sorted by name.
export async function loadMySubjects(apiClient: Client = client): Promise<SubjectResponse[]> {
  const { data, error, response } = await listMySubjects({ client: apiClient, throwOnError: false });
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /me/subjects failed (${response?.status ?? "no response"})`);
  return data;
}
