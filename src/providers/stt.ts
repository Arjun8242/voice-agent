import WebSocket from "ws";
import { SARVAM_API_KEY, SARVAM_STT_URL, STT_QUEUE_MAX } from "../config.js";

export interface SttHandlers {
  onSpeechStart(): void; 
  onSpeechEnd(): void;
  onPartial(text: string): void; 
  onFinal(text: string): void;
  onError(message: string): void;
}

export interface SttClient { 
    sendAudio(pcm: Buffer): void; 
    close(): void
}

export function streamstt(h: SttHandlers): SttClient {
  let socket: WebSocket | null = null;
  let queue: string[] = [];
  let pingTimer: ReturnType<typeof setInterval> | null = null;

  function open() {
    const ws = new WebSocket(SARVAM_STT_URL, { headers: { "api-subscription-key": SARVAM_API_KEY } });
    socket = ws;
    const cleanup = () => {
      if (pingTimer) clearInterval(pingTimer);
      pingTimer = null;
      if (socket === ws) socket = null;      // guard: a stale socket's close must not null a newer one
    };
    ws.on("open", () => {
      for (const m of queue) ws.send(m);
      queue = [];
      pingTimer = setInterval(() => { if (ws.readyState === WebSocket.OPEN) ws.ping(); }, 5000);
    });

    ws.on("message", (data) => {
      let ev: any; try { ev = JSON.parse(data.toString()); } catch { return; }
      switch (ev.event) {
        case "vad.speech_start": h.onSpeechStart(); break;
        case "vad.speech_end": h.onSpeechEnd(); break;
        case "transcript.partial":
        case "transcript.final": {
          const text = String(ev.text ?? "").trim();
          if (!text) return;
          ev.event === "transcript.final" ? h.onFinal(text) : h.onPartial(text);
        }
      }
    });
    ws.on("error", (e) => { h.onError(e.message); cleanup(); });
    ws.on("close", cleanup);
  }

  return {
    sendAudio(pcm) {
      const msg = JSON.stringify({ event: "audio_input", audio: pcm.toString("base64") });
      if (!socket) open();                                    
      if (socket?.readyState === WebSocket.OPEN) socket.send(msg);
      else if (queue.length < STT_QUEUE_MAX) queue.push(msg);
    },
    close() { socket?.close(); queue = []; },
  };
}