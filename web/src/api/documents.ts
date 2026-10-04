import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listDocuments, startUpload } from "./generated/sdk.gen";
import type { DocumentResponse } from "./generated/types.gen";

export type { DocumentResponse };

function sessionOver(error: unknown, response: Response | undefined): boolean {
  return error instanceof SessionExpiredError || response?.status === 401;
}

export async function loadDocuments(apiClient: Client = client): Promise<DocumentResponse[]> {
  const { data, error, response } = await listDocuments({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /documents failed (${response?.status ?? "no response"})`);
  return data;
}

// The API presigns a POST for this learner's key; the browser then sends the file straight to S3 (PRD §9.3).
export async function uploadPdf(file: File, apiClient: Client = client, post: typeof fetch = fetch): Promise<void> {
  const { data, error, response } = await startUpload({ client: apiClient, body: { file_name: file.name }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /uploads failed (${response?.status ?? "no response"})`);
  const form = new FormData();
  for (const [name, value] of Object.entries(data.fields)) form.append(name, value);
  form.append("file", file); // S3 ignores fields after the file
  const stored = await post(data.url, { method: "POST", body: form });
  if (!stored.ok) throw new Error(`Upload to storage failed (${stored.status})`);
}
