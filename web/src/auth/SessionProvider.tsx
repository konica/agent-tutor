import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { Button } from "../components/Button/Button";
import { type AuthClient, SessionExpiredError, sessionExpiry } from "./authClient";
import styles from "./SessionProvider.module.css";

export type Session = { name: string; signOut: () => void };

export const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession needs a SessionProvider");
  return session;
}

type Status = { kind: "loading" } | { kind: "ready"; name: string } | { kind: "expired" } | { kind: "error" };

type Props = { auth: AuthClient; loadMe: () => Promise<{ name: string }>; children: ReactNode };

// Signs the learner in (Keycloak), loads /me, and renders the app only for a live session (US-1).
export function SessionProvider({ auth, loadMe, children }: Props) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  const load = useCallback(async () => {
    setStatus({ kind: "loading" });
    try {
      await auth.init();
      const me = await loadMe();
      setStatus({ kind: "ready", name: me.name });
    } catch (e) {
      setStatus(e instanceof SessionExpiredError ? { kind: "expired" } : { kind: "error" });
    }
  }, [auth, loadMe]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => sessionExpiry.subscribe(() => setStatus({ kind: "expired" })), []);

  if (status.kind === "ready") {
    const session = { name: status.name, signOut: () => void auth.signOut() };
    return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
  }

  return (
    <main className={styles.screen}>
      {status.kind === "loading" && (
        <p role="status" className={styles.note}>
          Signing you in…
        </p>
      )}
      {status.kind === "expired" && (
        <div role="alert" className={styles.card}>
          <h1 className={styles.title}>Please sign in again</h1>
          <p className={styles.note}>Your session has ended.</p>
          <Button variant="primary" onClick={() => void auth.signIn()}>
            Sign in
          </Button>
        </div>
      )}
      {status.kind === "error" && (
        <div role="alert" className={styles.card}>
          <h1 className={styles.title}>Can't reach Smart Tutor</h1>
          <p className={styles.note}>Check your connection and try again.</p>
          <Button variant="secondary" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      )}
    </main>
  );
}
