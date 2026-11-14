import assert from 'node:assert/strict';
import { test } from 'node:test';

type Playback = typeof import('./playback.ts');

let copy = 0;
/** A fresh copy of the module for each test: its frame counters are module state. */
async function freshPlayback(): Promise<Playback> {
  copy += 1;
  return import(`./playback.ts?copy=${copy}`);
}

function frame(sentenceId: number): ArrayBuffer {
  const buffer = new ArrayBuffer(8);
  new DataView(buffer).setUint32(0, sentenceId, true);
  return buffer;
}

test('a late frame of a cut-off answer is dropped and the next answer plays', async () => {
  const { appendChunk, dropAudioSoFar } = await freshPlayback();
  assert.equal(appendChunk(frame(0)), true);
  assert.equal(appendChunk(frame(1)), true);

  dropAudioSoFar(); // the visitor cut in: sentences 0 and 1 belong to the old answer

  assert.equal(appendChunk(frame(1)), false); // still in flight when the answer was cancelled
  assert.equal(appendChunk(frame(0)), false);
  assert.equal(appendChunk(frame(2)), true); // the new answer continues the numbering
});

test('a reset before any audio arrived drops nothing', async () => {
  const { appendChunk, dropAudioSoFar } = await freshPlayback();
  dropAudioSoFar();
  assert.equal(appendChunk(frame(0)), true);
});

test('two resets in a row still let the next answer play', async () => {
  const { appendChunk, dropAudioSoFar } = await freshPlayback();
  appendChunk(frame(0));
  dropAudioSoFar();
  dropAudioSoFar();
  assert.equal(appendChunk(frame(0)), false);
  assert.equal(appendChunk(frame(1)), true);
});

test('frames arriving out of order are judged by the highest sentence seen', async () => {
  const { appendChunk, dropAudioSoFar } = await freshPlayback();
  appendChunk(frame(3)); // parallel TTS: sentence 3 can arrive before sentence 2
  appendChunk(frame(2));
  dropAudioSoFar();
  assert.equal(appendChunk(frame(3)), false);
  assert.equal(appendChunk(frame(4)), true);
});

test('a dropped late frame does not move the cut-off line', async () => {
  const { appendChunk, dropAudioSoFar } = await freshPlayback();
  appendChunk(frame(5));
  dropAudioSoFar();
  appendChunk(frame(2)); // dropped
  dropAudioSoFar();
  assert.equal(appendChunk(frame(5)), false);
  assert.equal(appendChunk(frame(6)), true);
});
