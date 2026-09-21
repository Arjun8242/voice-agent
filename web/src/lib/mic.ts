/**
 * Mic capture via AudioWorklet + WebSocket relay.
 * Streams raw Int16 PCM at 16kHz directly to the server — no buffering.
 */

let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;
let micStream: MediaStream | null = null;

export async function startMic(onChunk: (buf: ArrayBuffer) => void): Promise<void> {
  console.log("[Mic] Requesting microphone access with processing disabled...");
  micStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
    },
    video: false
  });
  console.log("[Mic] Microphone access granted. Starting stream...");

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule('/pcm-processor.js');

  const source = audioContext.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');

  let chunkCount = 0;
  workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
    chunkCount++;
    if (chunkCount % 20 === 0) {
      console.log(`[Mic] Sent ${chunkCount} chunks to WebSocket`);
    }
    onChunk(e.data);
  };

  source.connect(workletNode);
  // Connect to destination to keep the graph alive (silent output)
  workletNode.connect(audioContext.destination);
}

export function stopMic(): void {
  workletNode?.disconnect();
  workletNode = null;
  micStream?.getTracks().forEach((t) => t.stop());
  micStream = null;
  audioContext?.close();
  audioContext = null;
}
