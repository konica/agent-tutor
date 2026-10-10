import { SessionExpiredError } from "../auth/authClient";
import { failure, sessionOver } from "./documents";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { getChunk, recordHighlightMiss as postHighlightMiss } from "./generated/sdk.gen";

// A cited chunk as the viewer needs it to find the passage on its page (PRD §9.3). page and startIndex may be unknown.
export type ChunkPassage = { chunkId: string; documentId: string; page: number | null; startIndex: number | null; text: string };

// 404: the chunk is gone (its document deleted) or its document isn't readable by the caller.
export class ChunkNotFoundError extends Error {
  constructor() {
    super("Chunk not found");
    this.name = "ChunkNotFoundError";
  }
}

export async function loadChunk(chunkId: string, apiClient: Client = client): Promise<ChunkPassage> {
  const { data, error, response } = await getChunk({ client: apiClient, path: { chunk_id: chunkId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 404) throw new ChunkNotFoundError();
  if (!data) throw failure(error);
  return { chunkId: data.chunk_id, documentId: data.document_id, page: data.page, startIndex: data.start_index, text: data.text };
}

// Counts one "Couldn't highlight" view (PRD §10.1); the request carries nothing about the learner or the passage.
// Fire and forget: a lost count never bothers the learner.
export function recordHighlightMiss(apiClient: Client = client): void {
  postHighlightMiss({ client: apiClient, throwOnError: false }).catch(() => {});
}
