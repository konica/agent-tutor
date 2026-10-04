import { useCallback, useEffect, useState } from "react";

import type { DocumentResponse } from "../../api/documents";

export type DocumentsState = { documents: DocumentResponse[] | null; unavailable: boolean; refresh: () => Promise<void> };

// Loads the library now and every `pollMs`, so processing states update without a reload.
export function useDocuments(load: () => Promise<DocumentResponse[]>, pollMs: number): DocumentsState {
  const [documents, setDocuments] = useState<DocumentResponse[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await load());
      setUnavailable(false);
    } catch {
      setUnavailable(true); // a 401 is handled by the API client (SessionProvider shows "Please sign in again")
    }
  }, [load]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), pollMs);
    return () => clearInterval(timer);
  }, [refresh, pollMs]);

  return { documents, unavailable, refresh };
}
