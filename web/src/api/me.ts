import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { getMe } from "./generated/sdk.gen";
import type { MeResponse } from "./generated/types.gen";

// 401 and a failed token refresh both mean the session is over; anything else is an unreachable or broken API.
export async function loadMe(apiClient: Client = client): Promise<MeResponse> {
  const { data, error, response } = await getMe({ client: apiClient, throwOnError: false });
  // The generated client hands back an interceptor's error instead of throwing it.
  if (error instanceof SessionExpiredError || response?.status === 401) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /me failed (${response?.status ?? "no response"})`);
  return data;
}
