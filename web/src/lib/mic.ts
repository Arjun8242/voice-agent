/**
 * Mic capture via AudioWorklet + WebSocket relay.
 * Streams raw Int16 PCM at 16kHz directly to the server — no buffering.
 */

let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;
let micStream: MediaStream | null = null;

export async function startMic(onChunk: (buf: ArrayBuffer) => void): Promise<void> {
  micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });

  audioContext = new AudioContext();
  await audioContext.audioWorklet.addModule('/pcm-processor.js');

  const source = audioContext.createMediaStreamSource(micStream);
  workletNode = new AudioWorkletNode(audioContext, 'pcm-processor');

  workletNode.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
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
