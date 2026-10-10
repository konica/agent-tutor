import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { archiveDocument as postArchive, checkDuplicate, chooseSubjects, deleteDocument as sendDelete, getDocument, getDocumentFile, getSubjectSuggestions, getUpload, getUploadLimits, getUploadRateLimit, listDocuments, restoreDocument as postRestore, retryDocument, setDocumentTitle, startUpload } from "./generated/sdk.gen";
import type { DocumentDetailsResponse, DocumentResponse, SubjectSuggestionsResponse, SuggestionResponse, UploadLimitReachedResponse, UploadLimitsResponse, UploadRateLimitResponse, UploadStatusResponse } from "./generated/types.gen";

export type { DocumentResponse };
export type DocumentDetails = DocumentDetailsResponse;
export type UploadLimits = UploadLimitsResponse;
export type SubjectSuggestions = SubjectSuggestionsResponse;
export type Suggestion = SuggestionResponse;
export type UploadStatus = UploadStatusResponse;
export type UploadRateLimit = UploadRateLimitResponse;

// The learner reached an upload limit (PRD §11): the API refused the presigned POST until rateLimit.retry_at.
export class UploadLimitError extends Error {
  constructor(readonly rateLimit: UploadRateLimit, message = "") {
    super(message);
    this.name = "UploadLimitError";
  }
}

// The caller's own limits, and which one is reached (null while uploads are open).
export async function loadUploadRateLimit(apiClient: Client = client): Promise<UploadRateLimit> {
  const { data, error, response } = await getUploadRateLimit({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/rate-limit failed (${response?.status ?? "no response"})`);
  return data;
}

export function sessionOver(error: unknown, response: Response | undefined): boolean {
  return error instanceof SessionExpiredError || response?.status === 401;
}

// The server's `detail` is a string for 404/409 and a list of validation errors for 422.
// Without one the message is empty, so the learner never sees developer text.
export function failure(error: unknown): Error {
  const detail = (error as { detail?: unknown } | undefined)?.detail;
  if (typeof detail === "string") return new Error(detail);
  if (Array.isArray(detail)) {
    const messages = detail.map((d) => (d as { msg?: unknown }).msg).filter((m): m is string => typeof m === "string");
    if (messages.length) return new Error(messages.join("; "));
  }
  return new Error("");
}

// What the Library narrows by; every field is optional and they combine. Dates are YYYY-MM-DD calendar days, sent as the date input holds them.
export type DocumentFilters = {
  subject_ids?: string[];
  state?: DocumentResponse["state"];
  uploaded_from?: string;
  uploaded_to?: string;
  archived?: boolean; // true lists the archived documents; absent or false, the active ones
};

export async function loadDocuments(filters: DocumentFilters = {}, apiClient: Client = client): Promise<DocumentResponse[]> {
  const query = {
    ...(filters.subject_ids?.length ? { subject_id: filters.subject_ids } : {}),
    ...(filters.state ? { state: [filters.state] } : {}),
    ...(filters.uploaded_from ? { uploaded_from: filters.uploaded_from } : {}),
    ...(filters.uploaded_to ? { uploaded_to: filters.uploaded_to } : {}),
    ...(filters.archived ? { archived: true } : {}),
  };
  const { data, error, response } = await listDocuments({ client: apiClient, query, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /documents failed (${response?.status ?? "no response"})`);
  return data;
}

export class RetriesUsedUpError extends Error {
  constructor() {
    super("All processing attempts are used up");
    this.name = "RetriesUsedUpError";
  }
}

// Reprocesses a failed document's stored file (PRD §9.5). 409: the attempts are used up; the list then says so.
export async function retryProcessing(documentId: string, apiClient: Client = client): Promise<void> {
  const { error, response } = await retryDocument({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 409) throw new RetriesUsedUpError();
  if (!response?.ok) throw new Error(`POST /documents/${documentId}/retry failed (${response?.status ?? "no response"})`);
}

// Archiving takes a document out of search and My subjects; its content stays (PRD US-10). Repeating it is harmless.
export async function archiveDocument(documentId: string, apiClient: Client = client): Promise<DocumentResponse> {
  const { data, error, response } = await postArchive({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}

export async function restoreDocument(documentId: string, apiClient: Client = client): Promise<DocumentResponse> {
  const { data, error, response } = await postRestore({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}

// One document with its facts and summary (PRD US-10); a missing or foreign document reads "Document not found".
export async function loadDocumentDetails(documentId: string, apiClient: Client = client): Promise<DocumentDetails> {
  const { data, error, response } = await getDocument({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}

// Sets the learner's own display title; null goes back to the extracted title (PRD §9.4). 422 carries the reason to show.
export async function saveDocumentTitle(documentId: string, title: string | null, apiClient: Client = client): Promise<DocumentDetails> {
  const { data, error, response } = await setDocumentTitle({ client: apiClient, path: { document_id: documentId }, body: { title }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}

// 404 on delete: the document is already gone (deleted in another tab), which is what the learner wanted.
export class DocumentGoneError extends Error {
  constructor() {
    super("Document not found");
    this.name = "DocumentGoneError";
  }
}

// 409 on delete: the document is processing again (a retry); the message is the server's.
export class DocumentProcessingError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DocumentProcessingError";
  }
}

// Deleting removes the PDF, its text and chunks for good (PRD US-10c).
export async function deleteDocument(documentId: string, apiClient: Client = client): Promise<void> {
  const { error, response } = await sendDelete({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 404) throw new DocumentGoneError();
  if (response?.status === 409) throw new DocumentProcessingError(failure(error).message);
  if (!response?.ok) throw failure(error);
}

export type DocumentFile = { url: string; expiresAt: number; document: DocumentResponse }; // expiresAt: epoch ms

export class DocumentNotOpenableError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DocumentNotOpenableError";
  }
}

export class DocumentNotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "DocumentNotFoundError";
  }
}

// A short-lived link to the learner's own PDF for the viewer. 404: gone or not theirs; 409: still processing or failed.
export async function loadDocumentFile(documentId: string, apiClient: Client = client, now: () => number = Date.now): Promise<DocumentFile> {
  const { data, error, response } = await getDocumentFile({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 404) throw new DocumentNotFoundError("Document not found");
  if (response?.status === 409) throw new DocumentNotOpenableError(failure(error).message);
  if (!data) throw new Error(`GET /documents/${documentId}/file failed (${response?.status ?? "no response"})`);
  return { url: data.url, expiresAt: now() + data.expires_in * 1000, document: data.document };
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

// crypto.subtle hashes natively off the main thread, so a 50 MB file doesn't freeze the page.
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

// Only the caller's own library is searched (PRD D19): another learner's copy reads as "not in your library".
export async function findInLibrary(file: File, apiClient: Client = client): Promise<string | null> {
  const sha256 = await sha256Hex(file);
  const { data, error, response } = await checkDuplicate({ client: apiClient, body: { sha256 }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /documents/duplicate-check failed (${response?.status ?? "no response"})`);
  return data.document_id ?? null;
}

export type UploadEvents = { onStarted?: (documentId: string, uploadId: string) => void; onProgress?: (fraction: number) => void };
export type PostForm = (url: string, form: FormData, onProgress: (fraction: number) => void) => Promise<number>;

// fetch can't report upload progress; XMLHttpRequest can (the upload tray's bars). Resolves with the HTTP status.
export function postForm(url: string, form: FormData, onProgress: (fraction: number) => void): Promise<number> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => resolve(xhr.status);
    xhr.onerror = () => reject(new Error("Upload to storage failed (network error)"));
    xhr.onabort = () => reject(new Error("Upload to storage failed (aborted)"));
    xhr.send(form);
  });
}

// A 429 from anything but the upload limit (an edge limiter, a text body) has no retry time to show, so it is a plain failure.
function isUploadLimitBody(body: unknown): body is UploadLimitReachedResponse {
  if (typeof body !== "object" || body === null) return false;
  const { limit, retry_at } = body as Record<string, unknown>;
  return (limit === "hour" || limit === "day") && typeof retry_at === "string";
}

// The API presigns a POST for this learner's key and creates the row; the browser then sends the file straight to S3 (PRD §9.3).
// Callers check the file first with rejectionReason.
export async function uploadPdf(file: File, events: UploadEvents = {}, apiClient: Client = client, post: PostForm = postForm): Promise<void> {
  const { data, error, response } = await startUpload({ client: apiClient, body: { file_name: file.name }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (response?.status === 429 && isUploadLimitBody(error)) {
    const { detail, ...rateLimit } = error;
    throw new UploadLimitError(rateLimit, detail);
  }
  if (!data) throw new Error(`POST /uploads failed (${response?.status ?? "no response"})`);
  events.onStarted?.(data.document_id, data.upload_id);
  const form = new FormData();
  for (const [name, value] of Object.entries(data.fields)) form.append(name, value);
  form.append("file", file); // S3 ignores fields after the file
  const status = await post(data.url, form, (fraction) => events.onProgress?.(fraction));
  if (status < 200 || status >= 300) throw new Error(`Upload to storage failed (${status})`);
  events.onProgress?.(1);
}

// What became of an upload (PRD US-11): null outcome until the worker has hashed it; a duplicate points to the learner's document.
export async function loadUploadStatus(uploadId: string, apiClient: Client = client): Promise<UploadStatus> {
  const { data, error, response } = await getUpload({ client: apiClient, path: { upload_id: uploadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /uploads/${uploadId} failed (${response?.status ?? "no response"})`);
  return data;
}

// Three ranked suggestions for a document waiting for subjects (PRD §8 US-2b).
export async function loadSubjectSuggestions(documentId: string, apiClient: Client = client): Promise<SubjectSuggestions> {
  const { data, error, response } = await getSubjectSuggestions({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}

export async function saveSubjects(
  documentId: string,
  choice: { subject_ids: string[]; new_names: string[] },
  apiClient: Client = client,
): Promise<DocumentResponse> {
  const { data, error, response } = await chooseSubjects({ client: apiClient, path: { document_id: documentId }, body: choice, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}
