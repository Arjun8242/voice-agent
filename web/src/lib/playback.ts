/**
 * MSE-based streaming MP3 playback queue.
 * Receives binary frames [u32LE sentenceId][mp3 bytes] from server,
 * strips the prefix, and appends MP3 data to a SourceBuffer immediately.
 */

let ms: MediaSource | null = null;
let sb: SourceBuffer | null = null;
let audio: HTMLAudioElement | null = null;
let expectedSentenceId: number | null = 0;
const sentenceChunks = new Map<number, ArrayBuffer[]>();
const completedSentences = new Set<number>();
// sentence id -> where its audio starts on the media timeline (seconds). Used to tell which sentence is playing.
const sentenceStarts = new Map<number, number>();
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

  if (expectedSentenceId === null) {
    expectedSentenceId = sentenceId;
  }

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
  if (expectedSentenceId === null) return;

  const chunks = sentenceChunks.get(expectedSentenceId);
  
  if (chunks && chunks.length > 0) {
    draining = true;
    const chunk = chunks.shift()!;
    try {
      if (!sentenceStarts.has(expectedSentenceId)) {
        // sequence mode: a sentence starts where the audio buffered so far ends
        sentenceStarts.set(expectedSentenceId, sb.buffered.length ? sb.buffered.end(sb.buffered.length - 1) : 0);
      }
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

/** The last sentence whose audio has started by `time` seconds, or null if playback has not started. */
export function sentenceAt(starts: Map<number, number>, time: number): number | null {
  let found: number | null = null;
  for (const [id, start] of starts) {
    if (start < time && (found === null || id > found)) found = id;
  }
  return found;
}

/** The sentence being played right now (call before resetPlayback). */
export function currentSentenceId(): number | null {
  return audio ? sentenceAt(sentenceStarts, audio.currentTime) : null;
}

export function resetPlayback(audioEl: HTMLAudioElement): void {
  expectedSentenceId = null;
  sentenceChunks.clear();
  completedSentences.clear();
  sentenceStarts.clear();
  draining = false;
  streamDone = false;
  if (ms && ms.readyState === 'open') {
    try { ms.endOfStream(); } catch { /* ignore */ }
  }
  ms = null;
  sb = null;
  initPlayback(audioEl);
}
