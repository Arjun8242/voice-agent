/**
 * The resume upload before an interview (backend/server/interview_upload.py). The PDF goes as base64 in
 * JSON with the session id the WebSocket gave this page, so the server keeps the plan for this session.
 * The server answers with a one-line preview of what the interview will cover.
 */

export const MAX_PDF_BYTES = 5 * 1024 * 1024; // the server refuses more than about 5 MB
export const MAX_JD_CHARS = 50_000;
const UPLOAD_URL = '/interview/upload'; // vite.config.ts forwards it to the server in development

export interface PlanPreview {
  preview: string;
  topics: string[];
  fallback: boolean; // the analysis failed, so the questions are about the resume in general
}

export type UploadOutcome = { ok: true; plan: PlanPreview } | { ok: false; message: string };

/** A reason to refuse the file before sending it, or null. */
export function checkPdf(name: string, size: number): string | null {
  if (!name.toLowerCase().endsWith('.pdf')) return 'Choose a PDF file.';
  if (size > MAX_PDF_BYTES) return 'The PDF is larger than 5 MB.';
  return null;
}

export function toBase64(bytes: Uint8Array): string {
  let binary = '';
  const CHUNK = 0x8000; // String.fromCharCode takes its bytes as arguments: keep each call small
  for (let i = 0; i < bytes.length; i += CHUNK) binary += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  return btoa(binary);
}

export function uploadBody(sessionId: string, pdf: Uint8Array, jobDescription: string): string {
  return JSON.stringify({ session_id: sessionId, resume_pdf: toBase64(pdf), job_description: jobDescription.trim() });
}

/** The server's reply as an outcome; a 422 carries the message to show (a scan, not a PDF). */
export function outcomeFrom(status: number, body: unknown): UploadOutcome {
  if (status === 200 && isPlan(body)) return { ok: true, plan: body };
  const detail = typeof body === 'object' && body !== null ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === 'object' && detail !== null && typeof (detail as { message?: unknown }).message === 'string') {
    return { ok: false, message: (detail as { message: string }).message };
  }
  return { ok: false, message: 'The resume could not be uploaded. Try again.' };
}

function isPlan(value: unknown): value is PlanPreview {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<PlanPreview>;
  return typeof candidate.preview === 'string' && Array.isArray(candidate.topics);
}

export async function uploadResume(sessionId: string, file: File, jobDescription: string): Promise<UploadOutcome> {
  const problem = checkPdf(file.name, file.size);
  if (problem) return { ok: false, message: problem };
  const body = uploadBody(sessionId, new Uint8Array(await file.arrayBuffer()), jobDescription);
  try {
    const response = await fetch(UPLOAD_URL, { method: 'POST', headers: { 'content-type': 'application/json' }, body });
    return outcomeFrom(response.status, await response.json().catch(() => null));
  } catch {
    return { ok: false, message: 'Could not reach the server. Is it running?' };
  }
}
