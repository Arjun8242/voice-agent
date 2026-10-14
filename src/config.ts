import dotenv from "dotenv";

dotenv.config();

export const PORT = 3001;
export const SARVAM_API_KEY = process.env.SARVAM_API_KEY || "";
export const SARVAM_STT_URL =
    "wss://api.sarvam.ai/speech-to-text-realtime/ws" +
    "?language_code=en-IN" +
    "&model=saaras:v3-realtime" +
    "&stream_type=balanced";

export const STT_QUEUE_MAX = 50;

export const SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech/stream";
export const TTS_LANGUAGE = "en-IN";
export const TTS_MODEL = "bulbul:v3";
export const TTS_SPEAKER = "suhani";
export const TTS_OUTPUT_FORMAT = "mp3";
