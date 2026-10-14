export interface BargeInDeps {
    isAnswering(): boolean;
    isSpeaking(): boolean;
    interrupt(): void;
    confirmMs?: number;
}

export interface BargeInHandle {
    onSpeechStart(): void;
    onSpeechEnd(): void;
    dispose(): void;
}

export function createBargeIn(deps: BargeInDeps): BargeInHandle {
    const { isAnswering, isSpeaking, interrupt, confirmMs = 300 } = deps;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function clearTimer() {
        if (timer !== null) {
            clearTimeout(timer);
            timer = null;
        }
    }

    return {
        onSpeechStart() {
            if (!isAnswering()) return;               // pipeline idle — nothing to interrupt

            if (!isSpeaking()) {
                // Agent hasn't started playing audio yet — interrupt immediately
                interrupt();
                return;
            }

            // Agent audio is playing — wait confirmMs before interrupting
            // (avoids false triggers from mic bleed-through)
            clearTimer();
            timer = setTimeout(() => {
                timer = null;
                if (isAnswering()) interrupt();       // re-check: turn may have finished naturally
            }, confirmMs);
        },

        onSpeechEnd() {
            // User stopped speaking before confirmMs elapsed — cancel pending interrupt
            clearTimer();
        },

        dispose() {
            clearTimer();
        },
    };
}
