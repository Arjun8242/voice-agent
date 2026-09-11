/**
 * PCM Processor — AudioWorkletProcessor
 * Downsamples from source sample rate (e.g. 48kHz) to 16kHz,
 * quantizes to Int16, and posts raw binary frames to the main thread.
 * Each frame is a small ArrayBuffer (128 input samples → ~43 output samples).
 */
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._buffer = [];
    this._inputRate = 0; // set on first process()
    this._targetRate = 16000;
    this._ratio = 1;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;

    const samples = input[0]; // Float32Array, mono channel

    // Detect sample rate from AudioWorkletGlobalScope on first call
    if (this._inputRate === 0) {
      this._inputRate = sampleRate; // global in AudioWorkletGlobalScope
      this._ratio = this._inputRate / this._targetRate;
    }

    // Downsample: simple linear decimation (low overhead, acceptable for STT)
    const outLen = Math.floor(samples.length / this._ratio);
    const out = new Int16Array(outLen);

    for (let i = 0; i < outLen; i++) {
      const srcIdx = Math.floor(i * this._ratio);
      // Clamp and convert float32 [-1,1] → int16 [-32768, 32767]
      const clamped = Math.max(-1, Math.min(1, samples[srcIdx]));
      out[i] = clamped < 0 ? clamped * 32768 : clamped * 32767;
    }

    this.port.postMessage(out.buffer, [out.buffer]);
    return true;
  }
}

registerProcessor('pcm-processor', PcmProcessor);
