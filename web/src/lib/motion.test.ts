// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { targetLevel } from './motion.ts';

test('a character only moves its mouth while speaking, and is still when idle or thinking', () => {
  for (const now of [0, 400, 1234]) {
    assert.ok(targetLevel('speaking', now, false) >= 0.45);
    assert.equal(targetLevel('idle', now, true), 0);
    assert.equal(targetLevel('thinking', now, true), 0);
  }
});
