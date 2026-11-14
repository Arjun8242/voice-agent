// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { endInterviewMessage, reportStateFrom, startInterviewMessage } from './interview.ts';

const REPORT = { reviews: [], tips: ['Name the component first.'], average_score: null, dropped_quotes: 0 };

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
  assert.equal(reportStateFrom('ready', { tips: [] }), null);
  assert.equal(reportStateFrom('ready', 'not an object'), null);
  assert.equal(reportStateFrom('done', REPORT), null);
});
