// Run with `npm test` (Node's built-in runner).
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { blinkAmount, ease, lookToward, targetLevel } from './motion.ts';

test('a character only moves its mouth while speaking, and is still when idle or thinking', () => {
  for (const now of [0, 400, 1234]) {
    assert.ok(targetLevel('speaking', now, false) >= 0.45);
    assert.equal(targetLevel('idle', now, true), 0);
    assert.equal(targetLevel('thinking', now, true), 0);
  }
});

test('while listening it reacts only when the visitor is speaking', () => {
  assert.equal(targetLevel('listening', 500, false), 0);
  assert.ok(targetLevel('listening', 500, true) >= 0.3);
});

test('the level rises faster than it falls', () => {
  assert.ok(ease(0, 1) - 0 > 1 - ease(1, 0));
});

test('a blink closes the lids fully halfway through, then opens them', () => {
  assert.equal(blinkAmount(1070, 1000), 1);
  assert.equal(blinkAmount(1000, 1000), 0);
  assert.equal(blinkAmount(1200, 1000), 0);
});

test('pupils lean toward the pointer but never leave the eye', () => {
  const far = lookToward(10_000, 0);
  assert.ok(far.x <= 7 && far.x > 6.9 && far.y === 0);
  assert.deepEqual(lookToward(0, 0), { x: 0, y: 0 });
});
