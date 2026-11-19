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
  { name: 'neutral', label: 'Neutral', description: 'Calm, gentle nudges, hints when you ask.' },
  { name: 'strict', label: 'Strict', description: 'Exacting, questions your choices, no hints.' },
];

export function startInterviewMessage(persona: PersonaName): string {
  return JSON.stringify({ type: 'start_interview', persona });
}

export function endInterviewMessage(): string {
  return JSON.stringify({ type: 'end_interview' });
}

// ── The end-of-interview report (backend/interview/report.py Report) ────────────────────────

export type Band = 'strong' | 'ok' | 'weak';

export interface HeardAs {
  heard: string;
  read_as: string;
}

export interface Framework {
  key_points: string[];
  red_flags: string[];
  star: string;
  likely_followups: string[];
}

export interface AnswerReview {
  topic_id: string;
  topic: string;
  kind: string; // the stage: deep_dive, technical, behavioral, achievement
  question: string;
  answer: string;
  band: Band;
  framework: Framework;
  covered: string[]; // key points, as the framework words them
  missed: string[];
  improvement: string;
  gap: boolean; // a job requirement the resume did not show
  corrected: HeardAs[]; // terms the server fixed in the transcript
  read_by_meaning: HeardAs[]; // terms the evaluator read by meaning; never counted against the answer
}

export interface StageBand {
  kind: string;
  band: Band;
}

export interface InterviewReport {
  reviews: AnswerReview[];
  stages: StageBand[];
  strengths: string[];
  improvements: string[];
  gaps_touched: string[];
}

export const STAGE_NAMES: Record<string, string> = {
  deep_dive: 'Experience deep-dive',
  technical: 'Technical',
  behavioral: 'Behavioral',
  achievement: 'Achievement',
};

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
  return Array.isArray(candidate.reviews) && Array.isArray(candidate.stages) && Array.isArray(candidate.strengths);
}
