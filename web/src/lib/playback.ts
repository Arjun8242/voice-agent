/**
 * MSE-based streaming MP3 playback queue.
 * Receives binary frames [u32LE sentenceId][mp3 bytes] from server,
 * strips the prefix, and appends MP3 data to a SourceBuffer immediately.
 */

let ms: MediaSource | null = null;
let sb: SourceBuffer | null = null;
let audio: HTMLAudioElement | null = null;
const queue: ArrayBuffer[] = [];
let draining = false;
let streamDone = false;

export function initPlayback(audioEl: HTMLAudioElement): void {
  audio = audioEl;
  ms = new MediaSource();
  audio.src = URL.createObjectURL(ms);

  ms.addEventListener('sourceopen', () => {
    if (!ms) return;
    sb = ms.addSourceBuffer('audio/mpeg');
    sb.mode = 'sequence';
    sb.addEventListener('updateend', drain);
  });
}

export function appendChunk(frame: ArrayBuffer): void {
  // Strip 4-byte sentenceId prefix
  const mp3 = frame.slice(4);
  queue.push(mp3);
  drain();
}

export function signalDone(): void {
  streamDone = true;
  drain();
}

function drain(): void {
  if (draining || !sb || sb.updating) return;
  if (queue.length === 0) {
    if (streamDone && ms && ms.readyState === 'open') {
      ms.endOfStream();
      streamDone = false;
    }
    return;
  }
  draining = true;
  const chunk = queue.shift()!;
  try {
    sb.appendBuffer(chunk);
  } catch {
    // SourceBuffer error (e.g. quota exceeded) — skip chunk
  }
  draining = false;
}

export function resetPlayback(audioEl: HTMLAudioElement): void {
  queue.length = 0;
  draining = false;
  streamDone = false;
  if (ms && ms.readyState === 'open') {
    try { ms.endOfStream(); } catch { /* ignore */ }
  }
  ms = null;
  sb = null;
  initPlayback(audioEl);
}
