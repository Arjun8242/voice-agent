/**
 * MSE-based streaming MP3 playback queue.
 * Receives binary frames [u32LE sentenceId][mp3 bytes] from server,
 * strips the prefix, and appends MP3 data to a SourceBuffer immediately.
 */

let ms: MediaSource | null = null;
let sb: SourceBuffer | null = null;
let audio: HTMLAudioElement | null = null;
let expectedSentenceId = 0;
const sentenceChunks = new Map<number, ArrayBuffer[]>();
const completedSentences = new Set<number>();
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
  const view = new DataView(frame);
  const sentenceId = view.getUint32(0, true);
  const mp3 = frame.slice(4);

  if (!sentenceChunks.has(sentenceId)) {
    sentenceChunks.set(sentenceId, []);
  }
  sentenceChunks.get(sentenceId)!.push(mp3);
  drain();
}

export function markSentenceDone(sentenceId: number): void {
  completedSentences.add(sentenceId);
  drain();
}

export function signalDone(): void {
  streamDone = true;
  drain();
}

function drain(): void {
  if (draining || !sb || sb.updating) return;

  const chunks = sentenceChunks.get(expectedSentenceId);
  
  if (chunks && chunks.length > 0) {
    draining = true;
    const chunk = chunks.shift()!;
    try {
      sb.appendBuffer(chunk);
    } catch {
      // SourceBuffer error
    }
    draining = false;
    return;
  }

  // If no chunks left for the current sentence, check if it's completely downloaded
  if (completedSentences.has(expectedSentenceId)) {
    sentenceChunks.delete(expectedSentenceId);
    expectedSentenceId++;
    drain(); // trigger next sentence
    return;
  }

  // End of stream if all sentences are done
  if (streamDone && sentenceChunks.size === 0 && ms && ms.readyState === 'open') {
    ms.endOfStream();
    streamDone = false;
  }
}

export function resetPlayback(audioEl: HTMLAudioElement): void {
  expectedSentenceId = 0;
  sentenceChunks.clear();
  completedSentences.clear();
  draining = false;
  streamDone = false;
  if (ms && ms.readyState === 'open') {
    try { ms.endOfStream(); } catch { /* ignore */ }
  }
  ms = null;
  sb = null;
  initPlayback(audioEl);
}
