import { SessionExpiredError } from "../auth/authClient";
import { absoluteUrl } from "./absoluteUrl";
import { type Client } from "./generated/client";
import { client } from "./generated/client.gen";

export function apiBaseUrl(): string {
  return absoluteUrl(import.meta.env.VITE_API_URL || "http://localhost:10450");
}

type Options = {
  baseUrl: string;
  /** Refreshes first (updateToken(60)); rejects when the session is over. */
  getToken: () => Promise<string>;
  /** Called on a 401 or a failed refresh: the app shows "Please sign in again". */
  onUnauthorized: () => void;
  apiClient?: Client;
};

export function configureApiClient({ baseUrl, getToken, onUnauthorized, apiClient = client }: Options): void {
  apiClient.setConfig({ baseUrl });
  apiClient.interceptors.request.use(async (request) => {
    let token: string;
    try {
      token = await getToken();
    } catch {
      // A failed refresh means the session is over; callers tell this apart from an unreachable API by type.
      onUnauthorized();
      throw new SessionExpiredError();
    }
    request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  });
  apiClient.interceptors.response.use((response) => {
    if (response.status === 401) onUnauthorized();
    return response;
  });
}
