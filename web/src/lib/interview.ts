/**
 * Interview mode on the client: the modes and personas the page offers, and the messages it sends.
 * The server's side is start_interview / end_interview in backend/server/connection.py;
 * persona names must match backend/interview/personas.py.
 */

export type Mode = 'recruiter' | 'interview';
export type PersonaName = 'neutral' | 'strict';

// An interview ends after this long; must match INTERVIEW_MAX_SECONDS in backend/config.py.
export const INTERVIEW_LIMIT_SECONDS = 900;

/** The interviewers, in the order the arrows cycle them; each is drawn as a character (lib/characters.ts). */
export const PERSONAS: { name: PersonaName; character: 'sapwa' | 'sheru'; givesHints: boolean }[] = [
  { name: 'neutral', character: 'sapwa', givesHints: true },
  { name: 'strict', character: 'sheru', givesHints: false },
];

/** The persona next to this one, going forward (step 1) or back (step -1), wrapping around. */
export function stepPersona(current: PersonaName, step: 1 | -1): PersonaName {
  const index = PERSONAS.findIndex((p) => p.name === current);
  return PERSONAS[(index + step + PERSONAS.length) % PERSONAS.length].name;
}

/** The stage chips on the talk screen, in interview order; kind matches backend/interview/plan.py STAGES. */
export const STAGE_CHIPS: { kind: string; label: string }[] = [
  { kind: 'intro', label: 'intro' },
  { kind: 'deep_dive', label: 'deep dive' },
  { kind: 'technical', label: 'technical' },
  { kind: 'behavioral', label: 'behavioral' },
  { kind: 'achievement', label: 'flex' },
  { kind: 'wrap', label: 'wrap' },
];

/** How a chip looks for the live stage (the server's interview_stage): done before it, now on it. */
export function chipState(chipIndex: number, liveStage: string | null): 'done' | 'now' | 'todo' {
  const live = STAGE_CHIPS.findIndex((chip) => chip.kind === liveStage);
  if (live < 0 || chipIndex > live) return 'todo';
  return chipIndex === live ? 'now' : 'done';
}

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
