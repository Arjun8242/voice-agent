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
  };
};

export type LinkCard = {
  card_id: string;
  type: 'link';
  data: { label: string; url: string; description: string };
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

export type Card = ProjectDetailCard | LinkCard | BookingCard;

// Cards the visitor still has to act on: they stay when the visitor speaks, so a half-filled form is not lost.
export const KEEP_ACROSS_TURNS = new Set<Card['type']>(['slots', 'booking_form', 'booking_summary', 'cancel_confirm']);
