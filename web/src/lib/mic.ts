
let audioContext: AudioContext | null = null;
let workletNode: AudioWorkletNode | null = null;
let micStream: MediaStream | null = null;
let session = 0;

function release(stream: MediaStream | null, ctx: AudioContext | null): void {
  stream?.getTracks().forEach((t) => t.stop());
  if (ctx && ctx.state !== 'closed') void ctx.close();
}

export async function startMic(onChunk: (buf: ArrayBuffer) => void): Promise<void> {
  // Invalidate any in-flight start and tear down an existing capture.
  stopMic();
  const token = ++session;

  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
    video: false,
  });

  // stopMic() (or a newer startMic()) ran while the permission prompt was open.
  if (token !== session) {
    release(stream, null);
    return;
  }

  const ctx = new AudioContext({ sampleRate: 16000 });

  try {
    await ctx.audioWorklet.addModule('/pcm-processor.js');
  } catch (err) {
    release(stream, ctx);
    throw err;
  }

  if (token !== session) {
    release(stream, ctx);
    return;
  }

  const source = ctx.createMediaStreamSource(stream);
  const node = new AudioWorkletNode(ctx, 'pcm-processor');

  node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
    if (token === session) onChunk(e.data);
  };

  source.connect(node);
  // Connect to destination to keep the audio graph alive (silent output)
  node.connect(ctx.destination);

  micStream = stream;
  audioContext = ctx;
  workletNode = node;

  // AudioContext may start suspended in some browsers even after a click.
  // Assign state first so stopMic() can always tear this capture down.
  await ctx.resume().catch(() => {});
}

export function stopMic(): void {
  session++;

  workletNode?.disconnect();
  workletNode = null;

  const stream = micStream;
  micStream = null;
  stream?.getTracks().forEach((t) => t.stop());

  const ctx = audioContext;
  audioContext = null;
  if (ctx && ctx.state !== 'closed') void ctx.close();
}
