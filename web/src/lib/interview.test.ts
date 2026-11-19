// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { endInterviewMessage, reportStateFrom, startInterviewMessage } from './interview.ts';

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
