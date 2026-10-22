"""index.py: Mirror of src/server/index.ts, re-exporting FastAPI app from main.py."""
from .main import app, lifespan, websocket_endpoint

__all__ = ["app", "lifespan", "websocket_endpoint"]
