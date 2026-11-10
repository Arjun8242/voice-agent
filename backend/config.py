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
                os.environ[key.strip()] = value.strip().strip("\"'") 
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

CALENDAR_BACKEND = os.environ.get("CALENDAR_BACKEND", "fake")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REFRESH_TOKEN = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
GOOGLE_CALENDAR_ID = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
