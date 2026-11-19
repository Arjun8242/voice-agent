/**
 * The numbers behind a character's animation, as plain functions of time (Character.svelte draws them).
 * A character is perfectly still when idle: only speaking moves the mouth and body, only listening shows the ears.
 */

export type Phase = 'idle' | 'speaking' | 'listening' | 'thinking';

const BLINK_MS = 70; // half a blink: lids close over this long, then open over the same

/** How far the mouth opens (0 to 1) while speaking: a wobble that reads as talking. */
export function speakingLevel(now: number, seed = 0): number {
  return 0.45 + 0.5 * Math.abs(Math.sin(now / 85 + seed)) * (0.5 + 0.5 * Math.sin(now / 330));
}

/** The level a character moves toward: speech while speaking, the visitor's voice while listening, else rest. */
export function targetLevel(phase: Phase, now: number, visitorSpeaking: boolean, seed = 0): number {
  if (phase === 'speaking') return speakingLevel(now, seed);
  if (phase === 'listening' && visitorSpeaking) return 0.3 + 0.4 * Math.abs(Math.sin(now / 120));
  return 0;
}

/** One animation step toward the target: rises fast, falls slower, so the mouth does not snap shut. */
export function ease(level: number, target: number): number {
  return level + (target - level) * (target > level ? 0.35 : 0.12);
}

/** How closed the eyelids are (0 open, 1 shut), for a blink that started at blinkStart. */
export function blinkAmount(now: number, blinkStart: number): number {
  return Math.max(0, 1 - Math.abs(now - blinkStart - BLINK_MS) / BLINK_MS);
}

/** When the next blink starts: every few seconds, never in step with another character. */
export function nextBlink(now: number, random: () => number = Math.random): number {
  return now + 2400 + random() * 3000;
}

/** Pupil offset toward a point dx, dy away from the eyes, capped so the pupils stay in the eye. */
export function lookToward(dx: number, dy: number): { x: number; y: number } {
  const distance = Math.hypot(dx, dy) || 1;
  const reach = Math.min(1, distance / 300);
  return { x: (dx / distance) * 7 * reach, y: (dy / distance) * 6 * reach };
}
