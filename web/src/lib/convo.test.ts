// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { addAgentText, addVisitorWords, clock, dropTurn } from './convo.ts';

test('the pieces of one answer join into one message, a new turn starts another', () => {
  let feed = addAgentText([], 1, 'Walk me ');
  feed = addAgentText(feed, 1, 'through it.');
  feed = addVisitorWords(feed, 'Sure.');
  feed = addAgentText(feed, 2, 'Why Redis?');
  assert.deepEqual(feed.map((m) => [m.who, m.text]), [['agent', 'Walk me through it.'], ['user', 'Sure.'], ['agent', 'Why Redis?']]);
});

test('two turns in a row stay two messages even without visitor words between them', () => {
  const feed = addAgentText(addAgentText([], 1, 'Okay.'), 2, 'Next question.');
  assert.equal(feed.length, 2);
});

test('an interrupted turn loses its answer but keeps what the visitor said', () => {
  let feed = addAgentText([], 1, 'First answer.');
  feed = addVisitorWords(feed, 'Wait');
  feed = addAgentText(feed, 2, 'Second answer, cut off');
  const kept = dropTurn(feed, 2);
  assert.deepEqual(kept.map((m) => m.text), ['First answer.', 'Wait']);
});

test('empty visitor words add nothing', () => {
  assert.deepEqual(addVisitorWords([], '   '), []);
});

test('the timer reads minutes and padded seconds', () => {
  assert.equal(clock(0), '0:00');
  assert.equal(clock(65.9), '1:05');
  assert.equal(clock(900), '15:00');
});
