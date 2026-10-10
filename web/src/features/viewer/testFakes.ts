// Test-only fakes for the viewer: a document, its file link, and a PDF, so tests never reach the API or pdf.js.
import { vi } from "vitest";

import type { DocumentFile, DocumentResponse } from "../../api/documents";
import type { PdfDoc } from "./pdf";

export const fakeDocument = (extra: Partial<DocumentResponse> = {}): DocumentResponse =>
  ({ document_id: "d1", title: "ReAct", state: "ready", archived: false, authors: ["Yao"], year: 2022, subjects: [], ...extra }) as unknown as DocumentResponse;

export const fakeFile = (extra: Partial<DocumentResponse> = {}, url = "u1", expiresAt = Date.now() + 300_000): DocumentFile => ({
  url,
  expiresAt,
  document: fakeDocument(extra),
});

export const fakePdf = (numPages = 3): PdfDoc => ({
  numPages,
  destroy: vi.fn(),
  page: vi.fn(async () => ({ width: 600, height: 800, render: vi.fn(async () => {}) })),
});

const titles: Record<string, string> = { d1: "ReAct", d2: "PPO" };

// Viewer deps that serve "d1" (ReAct) and "d2" (PPO), each a 3-page PDF.
export function fakeViewerDeps() {
  return {
    loadFile: vi.fn(async (id: string) => fakeFile({ document_id: id, title: titles[id] ?? id }, `url-${id}`)),
    loadPdfDoc: vi.fn(async () => fakePdf()),
    restore: vi.fn(),
  };
}
