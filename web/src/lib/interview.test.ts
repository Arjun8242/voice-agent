// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { endInterviewMessage, reportStateFrom, chipState, startInterviewMessage, stepPersona } from './interview.ts';

const REPORT = { reviews: [], stages: [], strengths: ['Specific numbers.'], improvements: [], gaps_touched: [] };

test('the messages match what the server reads', () => {
  assert.deepEqual(JSON.parse(startInterviewMessage('strict')), { type: 'start_interview', persona: 'strict' });
  assert.deepEqual(JSON.parse(endInterviewMessage()), { type: 'end_interview' });
});

test('pending, failed and ready reports become page state', () => {
  assert.deepEqual(reportStateFrom('pending', undefined), { status: 'pending' });
  assert.deepEqual(reportStateFrom('failed', undefined), { status: 'failed' });
  assert.deepEqual(reportStateFrom('ready', REPORT), { status: 'ready', report: REPORT });
});

test('a ready status without a usable report, or an unknown status, is ignored', () => {
  assert.equal(reportStateFrom('ready', undefined), null);
  assert.equal(reportStateFrom('ready', { reviews: [], tips: [], average_score: 3 }), null); // an old-style report
  assert.equal(reportStateFrom('ready', 'not an object'), null);
  assert.equal(reportStateFrom('done', REPORT), null);
});

test('the interviewer arrows cycle through both personas in either direction', () => {
  assert.equal(stepPersona('neutral', 1), 'strict');
  assert.equal(stepPersona('strict', 1), 'neutral');
  assert.equal(stepPersona('neutral', -1), 'strict');
});

test('stage chips before the live stage are done, the live one is now, later ones wait', () => {
  assert.deepEqual([0, 1, 2, 3].map((i) => chipState(i, 'technical')), ['done', 'done', 'now', 'todo']);
  assert.equal(chipState(5, 'wrap'), 'now');
  assert.equal(chipState(0, null), 'todo'); // before the first stage message
  assert.equal(chipState(0, 'unknown_kind'), 'todo');
});
