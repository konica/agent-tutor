import { useCallback, useEffect, useRef, useState } from "react";

import {
  DocumentNotFoundError,
  DocumentNotOpenableError,
  loadDocumentFile,
  type DocumentFile,
  type DocumentResponse,
} from "../../api/documents";
import { SessionExpiredError } from "../../auth/authClient";

export type FileState =
  | { status: "loading" }
  | { status: "ready"; file: DocumentFile }
  | { status: "failed"; reason: "not-found" | "not-openable" | "error" };

const RENEW_BEFORE_MS = 30_000;

type Tagged = { documentId: string; state: FileState };

function reasonFor(error: unknown): "not-found" | "not-openable" | "error" {
  if (error instanceof DocumentNotFoundError) return "not-found";
  if (error instanceof DocumentNotOpenableError) return "not-openable";
  return "error";
}

// Fetches the short-lived link to a document's PDF and renews it before it expires. The viewer loads the PDF from the
// first link only and pdf.js fetches the rest from it, so renewing doesn't keep pdf.js's range requests working: a fetch
// after the first link expires fails, the viewer shows its error card, and Retry fetches a fresh link.
export function useDocumentFile(
  documentId: string,
  load: (id: string) => Promise<DocumentFile> = loadDocumentFile,
): { state: FileState; retry: () => void; setDocument: (d: DocumentResponse) => void } {
  const [tagged, setTagged] = useState<Tagged>({ documentId, state: { status: "loading" } });
  const [attempt, setAttempt] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const renew = (expiresAt: number) => {
      timer = setTimeout(
        () => {
          loadRef.current(documentId).then(
            (file) => {
              if (!live) return;
              setTagged({ documentId, state: { status: "ready", file } });
              renew(file.expiresAt);
            },
            () => {}, // keep the old link; Retry fetches again
          );
        },
        Math.max(0, expiresAt - RENEW_BEFORE_MS - Date.now()),
      );
    };

    setTagged({ documentId, state: { status: "loading" } });
    loadRef.current(documentId).then(
      (file) => {
        if (!live) return;
        setTagged({ documentId, state: { status: "ready", file } });
        renew(file.expiresAt);
      },
      (error: unknown) => {
        if (!live || error instanceof SessionExpiredError) return;
        setTagged({ documentId, state: { status: "failed", reason: reasonFor(error) } });
      },
    );

    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [documentId, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  const setDocument = useCallback((document: DocumentResponse) => {
    setTagged((t) => (t.state.status === "ready" ? { ...t, state: { status: "ready", file: { ...t.state.file, document } } } : t));
  }, []);

  // A render for a new documentId must not show the previous document's file.
  const state: FileState = tagged.documentId === documentId ? tagged.state : { status: "loading" };
  return { state, retry, setDocument };
}
