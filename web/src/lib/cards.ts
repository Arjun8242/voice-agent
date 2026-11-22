// Card payloads sent by the server in `ui_card` messages (built by backend/tools/*.py).
// The card_id is stable (e.g. "link:github"), so a card sent twice replaces itself.

export type ProjectDetailCard = {
  card_id: string;
  type: 'project_detail';
  data: {
    project_id: string;
    name: string;
    status: string;
    section: string;
    text: string;
    links: { repo: string; live: string | null; video: string | null };
    // Extras the card shows when the tool adds them; the header and tech pills are left out without them.
    one_line?: string;
    tech?: string[];
    sections?: string[];
  };
};

export type LinkCard = {
  card_id: string;
  type: 'link';
  data: { label: string; url: string; description: string };
};

// Skill cards (backend/tools/skills.py). A skill's evidence is a project (with a status) or an experience (with a role).
export type SkillEvidence = { id: string; kind: 'project' | 'experience'; name: string; status?: string; role?: string };
export type SkillEntry = { skill: string; category: string; evidence: SkillEvidence[] };

export type SkillsCard = {
  card_id: string;
  type: 'skills';
  data: { skills: SkillEntry[] };
};

export type SkillCard = {
  card_id: string;
  type: 'skill';
  data: SkillEntry;
};

// Booking cards (backend/tools/check_availability.py, start_booking.py, cancel_booking.py,
// graph/nodes/booking_gate.py, booking/execute.py). Every one after the slots list carries booking_id.
export type SlotsCard = {
  card_id: string;
  type: 'slots';
  data: { timezone: string; slots: { slot_id: string; label: string }[] };
};

export type BookingFormCard = {
  card_id: string;
  type: 'booking_form';
  data: { booking_id: string; slot_id: string; label: string; timezone: string; default_title: string };
};

export type BookingSummaryCard = {
  card_id: string;
  type: 'booking_summary';
  data: { booking_id: string; label: string; timezone: string; duration_minutes: number; name: string; email: string; title: string };
};

export type CancelConfirmCard = {
  card_id: string;
  type: 'cancel_confirm';
  data: { booking_id: string; label: string };
};

// From a booking_update after the calendar call; text is the server's fixed message.
export type BookingOutcomeCard = {
  card_id: string;
  type: 'booking_confirmed' | 'booking_slot_taken' | 'booking_calendar_failed' | 'booking_cancelled' | 'booking_cancel_failed';
  data: { booking_id: string; status: string; label: string; email: string; title: string; timezone: string; text?: string };
};

export type BookingCard = SlotsCard | BookingFormCard | BookingSummaryCard | CancelConfirmCard | BookingOutcomeCard;

export type Card = ProjectDetailCard | LinkCard | SkillsCard | SkillCard | BookingCard;

// Sends a ui_action to the server; the server checks every field and decides what happens.
export type CardActionHandler = (action: string, payload: Record<string, string>) => void;

// Cards the visitor still has to act on: they stay when the visitor speaks, so a half-filled form is not lost.
export const KEEP_ACROSS_TURNS = new Set<Card['type']>(['slots', 'booking_form', 'booking_summary', 'cancel_confirm']);
