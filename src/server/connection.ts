import { WebSocket } from "ws";
import { streamstt } from "../providers/stt.js";
import { createBargeIn } from "../pipeline/bargeIn.js";
import { answerTurn } from "../pipeline/answerTurn.js";
import { createSend } from "./protocol.js";
import { newConversation, startTurn, interruptTurn, finishTurn } from "./session.js";

export function handleConnection(ws: WebSocket): void {
    console.log("[server] Client connected");

    // Conversation state: history, sentenceCounter, agentSpeaking, current turn controller
    const conv = newConversation();

    // Send helper — no-op when socket is not OPEN, handles binary vs JSON framing
    const send = createSend(ws);

    // -------------------------------------------------------------------------
    // Barge-in: interrupt the agent when the user speaks over it
    // isAnswering: a turn is live when conv.current is non-null
    // isSpeaking:  agent audio is currently streaming to the browser
    // -------------------------------------------------------------------------
    const bargeIn = createBargeIn({
        isAnswering: () => conv.current !== null,
        isSpeaking:  () => conv.agentSpeaking,
        interrupt() {
            interruptTurn(conv);
            send("interrupted");
        },
    });

    // -------------------------------------------------------------------------
    // STT client — lazy-opens a Sarvam WebSocket on first audio frame received.
    // Callbacks drive bargeIn and answerTurn.
    // -------------------------------------------------------------------------
    const stt = streamstt({
        onSpeechStart() { bargeIn.onSpeechStart(); },
        onSpeechEnd()   { bargeIn.onSpeechEnd(); },

        onPartial(text) {
            send("transcript_partial", { text });
        },

        onFinal(text) {
            send("transcript_final", { text });
            const signal = startTurn(conv);
            answerTurn(text, conv, send, signal)
                .catch(console.error)
                .finally(() => finishTurn(conv, signal));
        },

        onError(message) {
            send("error", { message: `STT error: ${message}` });
        },
    });

    // -------------------------------------------------------------------------
    // Message handler
    // -------------------------------------------------------------------------
    ws.on("message", (raw: Buffer, isBinary: boolean) => {
        if (isBinary) {
            // Raw PCM from AudioWorklet → streamstt handles base64-encoding and queuing
            stt.sendAudio(raw);
            return;
        }

        // JSON — kept for scripts/test-hotpath.ts compatibility (send {type:"query"})
        let msg: any;
        try { msg = JSON.parse(raw.toString()); } catch { return; }

        if (msg.type === "query" && typeof msg.text === "string" && msg.text.trim()) {
            const signal = startTurn(conv);
            answerTurn(msg.text.trim(), conv, send, signal)
                .catch(console.error)
                .finally(() => finishTurn(conv, signal));
        }
    });

    // -------------------------------------------------------------------------
    // Cleanup on disconnect
    // -------------------------------------------------------------------------
    ws.on("close", () => {
        bargeIn.dispose();
        stt.close();
        interruptTurn(conv);
        console.log("[server] Client disconnected");
    });

    ws.on("error", (err) => console.error("[server] WS error:", err.message));
}
