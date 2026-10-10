import { useEffect, useRef, useState, type RefObject } from "react";

import { loadChunk as fetchChunk, type ChunkPassage } from "../../api/chunks";
import { SessionExpiredError } from "../../auth/authClient";
import type { Passage } from "./DocumentViewer";
import { findPassage, passageBoxes, type Box } from "./passage";
import type { PdfDoc } from "./pdf";

export type ChunkState = { status: "idle" } | { status: "loading" } | { status: "ready"; chunk: ChunkPassage } | { status: "failed" };

type Tagged = { chunkId: string | undefined; state: ChunkState };

const IDLE: ChunkState = { status: "idle" };
const LOADING: ChunkState = { status: "loading" };

// Fetches the cited chunk's text. Tagged by chunk id, so a late reply for the previous passage is dropped. An expired
// session leaves it loading: the app is signing the learner in again.
export function useChunk(chunkId: string | undefined, load: (id: string) => Promise<ChunkPassage> = fetchChunk): ChunkState {
  const [tagged, setTagged] = useState<Tagged>({ chunkId: undefined, state: IDLE });
  const loadRef = useRef(load);
  loadRef.current = load;

  useEffect(() => {
    if (chunkId === undefined) return;
    let live = true;
    loadRef.current(chunkId).then(
      (chunk) => {
        if (live) setTagged({ chunkId, state: { status: "ready", chunk } });
      },
      (error: unknown) => {
        if (live && !(error instanceof SessionExpiredError)) setTagged({ chunkId, state: { status: "failed" } });
      },
    );
    return () => {
      live = false;
    };
  }, [chunkId]);

  if (chunkId === undefined) return IDLE;
  return tagged.chunkId === chunkId ? tagged.state : LOADING;
}

// Whether the passage was found on its page: boxes in CSS px at zoom 100%, or null when it wasn't (or its chunk
// couldn't be fetched).
export type Highlight = { boxes: Box[] | null };

type Found = { chunkId: string; page: number; boxes: Box[] | null };

// Finds the passage on the text layer of its page once the PDF, the page, and the chunk are all there. Null until then,
// and whenever another page is shown. `afterRender` resolves when the queued canvas render is done, so the boxes (and
// the scroll to them) come once the page has its size.
export function usePassageHighlight(
  doc: PdfDoc | null,
  page: number,
  chunk: ChunkState,
  passage: Passage | undefined,
  afterRender: () => Promise<void>,
): Highlight | null {
  const [found, setFound] = useState<Found | null>(null);
  const afterRenderRef = useRef(afterRender);
  afterRenderRef.current = afterRender;
  const chunkId = passage?.chunkId;
  const target = passage?.page;
  const ready = chunk.status === "ready" ? chunk.chunk : null;
  const failed = chunk.status === "failed";

  useEffect(() => {
    if (!doc || chunkId === undefined || page !== target) return;
    if (failed) {
      setFound({ chunkId, page, boxes: null });
      return;
    }
    if (!ready) return;
    let live = true;
    afterRenderRef
      .current()
      .then(() => doc.page(page))
      .then((pdfPage) => pdfPage.textItems())
      .then(
        (items) => {
          const span = findPassage(items, ready.text, ready.startIndex);
          const boxes = span ? passageBoxes(items, span) : [];
          return boxes.length ? boxes : null;
        },
        () => null,
      )
      .then((boxes) => {
        if (live) setFound({ chunkId, page, boxes });
      });
    return () => {
      live = false;
    };
  }, [doc, page, chunkId, target, ready, failed]);

  if (!passage || !found || found.chunkId !== passage.chunkId || found.page !== passage.page || page !== passage.page) return null;
  return found;
}

// Once per passage object: the first time it is drawn, scroll it to a third from the top of the canvas area; if it
// couldn't be highlighted, count the miss (PRD §10.1). Returning to its page later does neither again.
export function usePassageReveal(
  highlight: Highlight | null,
  passage: Passage | undefined,
  scale: number,
  canvasAreaRef: RefObject<HTMLElement | null>,
  pageRef: RefObject<HTMLElement | null>,
  recordMiss: () => void,
): void {
  const boxes = highlight?.boxes ?? null;
  const missed = highlight !== null && boxes === null;

  const scrolledFor = useRef<Passage>(undefined);
  useEffect(() => {
    if (!boxes || !passage || scrolledFor.current === passage) return;
    scrolledFor.current = passage;
    const area = canvasAreaRef.current;
    const pageEl = pageRef.current;
    if (area && pageEl) area.scrollTop = Math.max(0, pageEl.offsetTop + boxes[0]!.y * scale - area.clientHeight / 3);
  }, [boxes, passage, scale, canvasAreaRef, pageRef]);

  const missedFor = useRef<Passage>(undefined);
  useEffect(() => {
    if (!missed || !passage || missedFor.current === passage) return;
    missedFor.current = passage;
    recordMiss();
  }, [missed, passage, recordMiss]);
}
