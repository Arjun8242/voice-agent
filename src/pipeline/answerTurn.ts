import { streamtts } from "../providers/tts";
import type { Send } from "../server/protocol";
import type { Conversation } from "../server/session";
import { FALLBACK_ANSWER, generateAnswerStream } from "../services/rag/llm";
import { retrieveLocal } from "../services/rag/local_retriever";
import { extractNextSentence } from "./sentence";

type AnswerState = Pick<Conversation, "history" | "agentSpeaking" | "sentenceCounter">

export async function speakSentence(
    send: Send, sentenceId: number, text: string, signal: AbortSignal,
    firstAudioRef: { sentMs: number | null }, elapsed: () => number, onAudio: () => void
) {
    const idBuf = Buffer.allocUnsafe(4);
    idBuf.writeUInt32LE(sentenceId, 0);
    let producedFirst = false;
    try {
        await streamtts(text, signal, (mp3) => {
            send(Buffer.concat([idBuf, Buffer.from(mp3)]));
            if (firstAudioRef.sentMs === null) {
                firstAudioRef.sentMs = elapsed();
                producedFirst = true;
                onAudio(); // called once — first audio chunk of the entire turn
            }
        });
    } catch (err: any) {
        if (err.name !== "AbortError") console.error(`[TTS] sentence ${sentenceId}:`, err.message);
    } finally {
        send("tts_end", { sentenceId, isFirst: producedFirst, firstAudioLatencyMs: producedFirst ? firstAudioRef.sentMs : null });
    }
}

export async function answerTurn(query: string, state: AnswerState, send: Send, signal: AbortSignal) {
    const intial_time = performance.now();
    const elapsed = () => Math.round(performance.now() - intial_time);

    const firstAudio = { sentMs: null as number | null };
    const speaking: Promise<void>[] = [];
    let sentenceBuffer = "", answer = "", FirstToken = false;

    const speak = (sentence: string) => {
        if (signal.aborted) return;

        const id = state.sentenceCounter++;
        speaking.push(speakSentence(send, id, sentence, signal, firstAudio, elapsed,
            () => { state.agentSpeaking = true; }));
    };

    try {
        const rag = await retrieveLocal(query, 3);

        if (signal.aborted) return;

        send("metric", {
            stage: "rag_complete",
            ragLatencyMs: rag.latencyMs
        });

        if (rag.chunks.length === 0) {
            speak(FALLBACK_ANSWER);
        }
        else{
            const { stream } = await generateAnswerStream(query, rag, state.history);

            for await (const chunk of stream) {

                if (signal.aborted) break;

                const token = chunk.text();

                if (!token) continue;

                if (!FirstToken) { FirstToken = true; 
                    send("metric", { 
                        stage: "gemini_first_token", 
                        ttftMs: elapsed()
                    });
                }
                
                answer += token;
                send("assistant_text", { text: token });
                
                sentenceBuffer += token;
                let next = extractNextSentence(sentenceBuffer);

                while (next) { 
                    speak(next.sentence); 
                    sentenceBuffer = next.remaining; 
                    next = extractNextSentence(sentenceBuffer);
                }
            }

            if (sentenceBuffer.trim()) speak(sentenceBuffer.trim());
        }

        if (answer.trim()) {
            state.history.push({ role: "user", text: query });
            state.history.push({ role: "assistant", text: answer.trim() });
            if (state.history.length > 6) state.history = state.history.slice(-6);
        }
    
    } catch (err: any) {
        if (err.name !== "AbortError") {
            console.error("[answerTurn]", err.message);
            if (!signal.aborted && speaking.length === 0) speak(FALLBACK_ANSWER); 
        }
    }

    await Promise.all(speaking); 
    if (signal.aborted) return;
    state.agentSpeaking = false;
    send("done", { totalMs: elapsed() });
  
}
