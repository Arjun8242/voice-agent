/**
 * PCM Processor — AudioWorkletProcessor
 * Accumulates samples into a 1600-sample (100 ms @ 16 kHz) persistent buffer.
 * Decimates only when AudioContext is not already at 16 kHz.
 * Emits Int16 PCM as transferable ArrayBuffer to the main thread.
 */
class PcmProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Int16Array(1600);
    this.n = 0;
    this.ratio = 1; // overridden on first process() if sampleRate != 16000
    this.initialized = false;
  }

  process(inputs) {
    const ch = inputs[0]?.[0];
    if (!ch) return true;

    if (!this.initialized) {
      this.ratio = sampleRate / 16000; // sampleRate is global in AudioWorkletGlobalScope
      this.initialized = true;
    }

    if (this.ratio === 1) {
      // AudioContext is already 16 kHz — no decimation needed
      for (let i = 0; i < ch.length; i++) {
        const s = Math.max(-1, Math.min(1, ch[i]));
        this.buf[this.n++] = s < 0 ? s * 32768 : s * 32767;
        if (this.n === this.buf.length) {
          const out = this.buf.slice().buffer;
          this.port.postMessage(out, [out]);
          this.n = 0;
        }
      }
    } else {
      // Decimate from source rate to 16 kHz
      const outLen = Math.floor(ch.length / this.ratio);
      for (let i = 0; i < outLen; i++) {
        const s = Math.max(-1, Math.min(1, ch[Math.floor(i * this.ratio)]));
        this.buf[this.n++] = s < 0 ? s * 32768 : s * 32767;
        if (this.n === this.buf.length) {
          const out = this.buf.slice().buffer;
          this.port.postMessage(out, [out]);
          this.n = 0;
        }
      }
    }

    return true;
  }
}

registerProcessor('pcm-processor', PcmProcessor);
