import { Turn } from "../services/rag/llm.js";


export interface Conversation {
    history: Turn[];
    sentenceCounter: number;
    agentSpeaking: boolean;
    current: AbortController | null;
}

export function newConversation(): Conversation {
    return { history: [], sentenceCounter: 0, agentSpeaking: false, current: null }
}

/**
 * Start a new turn. Aborts any in-flight turn, creates a fresh controller,
 * resets agentSpeaking. Returns the signal to pass into answerTurn().
 */
export function startTurn(c: Conversation): AbortSignal {
    c.current?.abort();
    c.current = new AbortController();
    c.agentSpeaking = false;
    return c.current.signal;
}

/**
 * Interrupt the current turn immediately (barge-in, connection close).
 * Aborts the controller and clears it so isAnswering() returns false.
 */
export function interruptTurn(c: Conversation): void {
    c.current?.abort();
    c.current = null;
    c.agentSpeaking = false;
}

/**
 * Called in the .finally() after answerTurn resolves.
 * Only clears `current` if this signal still belongs to the active turn —
 * guards against a stale .finally() from an interrupted turn clearing a
 * newer turn's controller.
 */
export function finishTurn(c: Conversation, signal: AbortSignal): void {
    if (c.current?.signal === signal) c.current = null;
}