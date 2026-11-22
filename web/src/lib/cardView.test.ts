// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { hostOf, initials, needsCollapse, projectLinks, statusView } from './cardView.ts';

test('only a shipped project gets the shipped pill, an unknown status is shown as written', () => {
  assert.equal(statusView('shipped').tone, 'shipped');
  assert.equal(statusView('runnable_not_deployed').label, 'Runs locally');
  assert.deepEqual(statusView('paused'), { label: 'paused', tone: 'wip' });
});

test('a missing project link keeps its slot with no href, so the card can grey it out', () => {
  const links = projectLinks({ repo: 'https://github.com/a/b', live: null, video: '' });
  assert.deepEqual(links.map((l) => [l.key, l.href]), [['repo', 'https://github.com/a/b'], ['live', null], ['video', null]]);
});

test('only long text starts collapsed', () => {
  assert.equal(needsCollapse('short'), false);
  assert.equal(needsCollapse('x'.repeat(400)), true);
});

test('a link card shows the host without scheme or trailing slash, and two-letter initials', () => {
  assert.equal(hostOf('https://github.com/Arjun8242/'), 'github.com/Arjun8242');
  assert.equal(initials('GitHub Profile'), 'GP');
  assert.equal(initials('LinkedIn'), 'L');
});
