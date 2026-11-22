// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { groupSlotsByDay, outcomeView, parseSlotLabel } from './bookingView.ts';

test('a server slot label is split into its day, time and zone', () => {
  assert.deepEqual(parseSlotLabel('Tue 02 Dec, 10:00 IST'), { weekday: 'Tue', day: '02', month: 'Dec', time: '10:00', zone: 'IST' });
  assert.equal(parseSlotLabel('some other format'), null);
});

test('slots on the same day share one group, and a label in another shape still gets a button', () => {
  const days = groupSlotsByDay([
    { slot_id: 'a', label: 'Tue 02 Dec, 10:00 IST' },
    { slot_id: 'b', label: 'Tue 02 Dec, 14:30 IST' },
    { slot_id: 'c', label: 'Wed 03 Dec, 10:00 IST' },
    { slot_id: 'd', label: 'odd label' },
  ]);
  assert.deepEqual(days.map((d) => [d.day, d.times.map((t) => t.time)]), [
    ['Tue 02 Dec', ['10:00', '14:30']],
    ['Wed 03 Dec', ['10:00']],
    ['odd label', ['odd label']],
  ]);
});

test('a taken slot or a failed calendar call is a warning, never shown as done', () => {
  assert.equal(outcomeView('booking_slot_taken').tone, 'warn');
  assert.equal(outcomeView('booking_calendar_failed').tone, 'warn');
  assert.equal(outcomeView('booking_cancelled').tone, 'good');
});
