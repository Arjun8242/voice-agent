import os
from pathlib import Path


def _load_env() -> None:
    candidates = [
        Path(".env"),
        Path(__file__).resolve().parent / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    ]
    for path in candidates:
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
            break


_load_env()

PORT = int(os.environ.get("PORT", "3001"))
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_STT_URL = (
    "wss://api.sarvam.ai/speech-to-text-realtime/ws"
    "?language_code=en-IN"
    "&model=saaras:v3-realtime"
    "&stream_type=fast"
)
STT_QUEUE_MAX = 50

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech/stream"
TTS_LANGUAGE = "en-IN"
TTS_MODEL = "bulbul:v3"
TTS_SPEAKER = "suhani"
TTS_OUTPUT_FORMAT = "mp3"

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
