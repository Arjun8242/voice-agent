/**
 * Interview mode on the client: the modes and personas the page offers, and the messages it sends.
 * The server's side is start_interview / end_interview in backend/server/connection.py;
 * persona names must match backend/interview/personas.py.
 */

export type Mode = 'recruiter' | 'interview';
export type PersonaName = 'neutral' | 'strict';

export const MODES: { value: Mode; label: string }[] = [
  { value: 'recruiter', label: 'Ask about Arjun' },
  { value: 'interview', label: 'Mock interview' },
];

export const PERSONAS: { name: PersonaName; label: string; description: string }[] = [
  { name: 'neutral', label: 'Neutral', description: 'Calm, up to two follow-ups per topic, hints when you ask.' },
  { name: 'strict', label: 'Strict', description: 'Exacting, questions your choices, no hints.' },
];

export function startInterviewMessage(persona: PersonaName): string {
  return JSON.stringify({ type: 'start_interview', persona });
}

export function endInterviewMessage(): string {
  return JSON.stringify({ type: 'end_interview' });
}

// ── The end-of-interview report (backend/interview/evaluate.py Report) ──────────────────────

export interface QuotedPoint {
  point: string;
  quote: string; // copied from the project notes; the server dropped any it could not find there
}

export interface QuotedClaim {
  claim: string;
  quote: string;
}

export interface AnswerReview {
  topic_id: string;
  topic: string;
  question: string;
  answer: string;
  score: number; // 1-5
  correct_points: QuotedPoint[];
  missing_points: QuotedPoint[];
  incorrect_claims: QuotedClaim[];
  unverifiable_claims: string[];
}

export interface InterviewReport {
  reviews: AnswerReview[];
  tips: string[];
  average_score: number | null;
  dropped_quotes: number;
}

export type ReportState = { status: 'pending' } | { status: 'failed' } | { status: 'ready'; report: InterviewReport };

/** The interview_report message as page state, or null if it is not one we understand. */
export function reportStateFrom(status: unknown, report: unknown): ReportState | null {
  if (status === 'pending' || status === 'failed') return { status };
  if (status === 'ready' && isReport(report)) return { status, report };
  return null;
}

function isReport(value: unknown): value is InterviewReport {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<InterviewReport>;
  return Array.isArray(candidate.reviews) && Array.isArray(candidate.tips);
}
