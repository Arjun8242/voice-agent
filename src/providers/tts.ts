import { SARVAM_TTS_URL, SARVAM_API_KEY, TTS_LANGUAGE, TTS_MODEL, TTS_SPEAKER, TTS_OUTPUT_FORMAT } from "../config";


export async function streamtts(text: string, interuptSignal: AbortSignal, onChunk: (mp3: Uint8Array) => void): Promise<void> {
    const res = await fetch(SARVAM_TTS_URL, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "api-subscription-key": SARVAM_API_KEY
        },
        body: JSON.stringify({
            text,
            language_code: TTS_LANGUAGE,
            model: TTS_MODEL,
            speaker: TTS_SPEAKER,
            output_audio_codec: TTS_OUTPUT_FORMAT
        }),
        signal: interuptSignal
    })

    if (!res.ok) {
        throw new Error(`TTS failed: ${res.status}: ${(await res.text()).slice(0, 100)}`)
    }

    if (!res.body) {
        throw new Error("TTS no response body")
    }

    const reader = res.body.getReader()

    try {
        while (true) {

            if (interuptSignal.aborted) {
                console.log("TTS stream aborted")
                return
            }

            const { done, value } = await reader.read()

            if (done) return

            if (value) {
                onChunk(value)
            }
        }
    }
    finally {
        reader.cancel().catch((err) => console.error("TTS reader cancel", err))
    }
}