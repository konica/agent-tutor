// Test-only fakes for the viewer: a document, its file link, a PDF, and a cited chunk, so tests never reach the API or
// pdf.js.
import { vi } from "vitest";

import type { ChunkPassage } from "../../api/chunks";
import type { DocumentFile, DocumentResponse } from "../../api/documents";
import type { TextItem } from "./passage";
import type { PdfDoc } from "./pdf";

export const fakeDocument = (extra: Partial<DocumentResponse> = {}): DocumentResponse =>
  ({ document_id: "d1", title: "ReAct", state: "ready", archived: false, authors: ["Yao"], year: 2022, subjects: [], ...extra }) as unknown as DocumentResponse;

export const fakeFile = (extra: Partial<DocumentResponse> = {}, url = "u1", expiresAt = Date.now() + 300_000): DocumentFile => ({
  url,
  expiresAt,
  document: fakeDocument(extra),
});

// Every page has the same text layer, `items`.
export const fakePdf = (numPages = 3, items: TextItem[] = []): PdfDoc => ({
  numPages,
  destroy: vi.fn(),
  page: vi.fn(async () => ({ width: 600, height: 800, render: vi.fn(async () => {}), textItems: vi.fn(async () => items) })),
});

const titles: Record<string, string> = { d1: "ReAct", d2: "PPO" };

// Viewer deps that serve "d1" (ReAct) and "d2" (PPO), each a 3-page PDF without text, and any chunk as page 2 of d1.
export function fakeViewerDeps() {
  return {
    loadFile: vi.fn(async (id: string) => fakeFile({ document_id: id, title: titles[id] ?? id }, `url-${id}`)),
    loadPdfDoc: vi.fn(async (_url: string) => fakePdf()),
    restore: vi.fn(),
    loadChunk: vi.fn(async (id: string): Promise<ChunkPassage> => ({ chunkId: id, documentId: "d1", page: 2, startIndex: 0, text: "Cited text here." })),
    recordMiss: vi.fn(),
  };
}
