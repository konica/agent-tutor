// The sign-in boundary the app depends on; keycloakClient.ts implements it, tests fake it.
export type AuthClient = {
  /** Resolves once the learner is signed in (redirects to Keycloak first if needed). */
  init(): Promise<void>;
  /** A token valid for at least 60 more seconds; rejects when the session can't be refreshed. */
  getToken(): Promise<string>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
};

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

const listeners = new Set<() => void>();

/** The API client reports an ended session here; SessionProvider listens. */
export const sessionExpiry = {
  notify() {
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
