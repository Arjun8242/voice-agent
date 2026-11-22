/**
 * What the booking cards show, as plain functions of a card's data (the components in components/booking/ draw them).
 * Slot labels come from the server as "%a %d %b, %H:%M %Z" (backend/booking/availability.py slot_label).
 */

import type { BookingOutcomeCard, SlotsCard } from './cards.ts';

// The meeting length the booking form promises; the server's booking rules fix it at 30 minutes.
export const MEETING_MINUTES = 30;

export type SlotLabel = { weekday: string; day: string; month: string; time: string; zone: string };
export type DayOfSlots = { day: string; times: { slot_id: string; time: string }[] };
export type OutcomeView = { icon: string; tone: 'good' | 'warn'; title: string };

const SLOT_LABEL = /^(\S+) (\d{1,2}) (\S+), (\d{2}:\d{2}) (.+)$/;

const OUTCOME_VIEWS: Record<BookingOutcomeCard['type'], OutcomeView> = {
  booking_confirmed: { icon: '✓', tone: 'good', title: 'Booked' },
  booking_cancelled: { icon: '✓', tone: 'good', title: 'Cancelled' },
  booking_slot_taken: { icon: '!', tone: 'warn', title: 'That time was just taken' },
  booking_calendar_failed: { icon: '!', tone: 'warn', title: 'Could not book it' },
  booking_cancel_failed: { icon: '!', tone: 'warn', title: 'Could not cancel' },
};

/** The parts of a slot label, or null if the server ever sends a label in another shape. */
export function parseSlotLabel(label: string): SlotLabel | null {
  const match = SLOT_LABEL.exec(label);
  if (!match) return null;
  const [, weekday, day, month, time, zone] = match;
  return { weekday, day, month, time, zone };
}

/** Slots grouped under their day, in the order given. An unparseable label becomes its own group. */
export function groupSlotsByDay(slots: SlotsCard['data']['slots']): DayOfSlots[] {
  const days: DayOfSlots[] = [];
  for (const slot of slots) {
    const parts = parseSlotLabel(slot.label);
    const day = parts ? `${parts.weekday} ${parts.day} ${parts.month}` : slot.label;
    const entry = { slot_id: slot.slot_id, time: parts ? parts.time : slot.label };
    const group = days.find((d) => d.day === day);
    if (group) group.times.push(entry);
    else days.push({ day, times: [entry] });
  }
  return days;
}

/** The icon, colour and heading of a booking outcome card; the body text is the server's own message. */
export function outcomeView(type: BookingOutcomeCard['type']): OutcomeView {
  return OUTCOME_VIEWS[type];
}
