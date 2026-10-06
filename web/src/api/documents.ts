import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { getUploadLimits, listDocuments, retryDocument, startUpload } from "./generated/sdk.gen";
import type { DocumentResponse, UploadLimitsResponse } from "./generated/types.gen";

export type { DocumentResponse };
export type UploadLimits = UploadLimitsResponse;

function sessionOver(error: unknown, response: Response | undefined): boolean {
  return error instanceof SessionExpiredError || response?.status === 401;
}

export async function loadDocuments(apiClient: Client = client): Promise<DocumentResponse[]> {
  const { data, error, response } = await listDocuments({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /documents failed (${response?.status ?? "no response"})`);
  return data;
}

// Reprocesses a failed document's stored file (PRD §9.5). 409: the attempts are used up; the list then says so.
export async function retryProcessing(documentId: string, apiClient: Client = client): Promise<void> {
  const { error, response } = await retryDocument({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!response?.ok) throw new Error(`POST /documents/${documentId}/retry failed (${response?.status ?? "no response"})`);
}

export async function loadUploadLimits(apiClient: Client = client): Promise<UploadLimits> {
  const { data, error, response } = await getUploadLimits({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/limits failed (${response?.status ?? "no response"})`);
  return data;
}

const MIB = 1_048_576;

// Rounded up, so a file just over the limit never reads as equal to it.
export const megabytes = (bytes: number) => String(Math.ceil((bytes / MIB) * 10) / 10);

function isPdf(file: File): boolean {
  return file.type === "application/pdf" || (file.type === "" && file.name.toLowerCase().endsWith(".pdf"));
}

// Checked before upload (PRD §8 US-2); the presigned POST enforces the size again on the server.
// Without limits (null) only the size check is skipped; the caller must not upload an unchecked file.
export function rejectionReason(file: File, limits: UploadLimits | null): string | null {
  if (!isPdf(file)) return "Not uploaded. Only PDF files can be uploaded.";
  if (file.size === 0) return "Not uploaded. This file is empty.";
  if (limits && file.size > limits.max_bytes)
    return `Not uploaded. This file is ${megabytes(file.size)} MB; the limit is ${megabytes(limits.max_bytes)} MB.`;
  return null;
}

// The API presigns a POST for this learner's key; the browser then sends the file straight to S3 (PRD §9.3). Callers check the file first with rejectionReason.
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
