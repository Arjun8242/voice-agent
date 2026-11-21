"""index.py: Mirror of src/server/index.ts, re-exporting FastAPI app from main.py."""
from .main import app, health_check, lifespan, websocket_endpoint

__all__ = ["app", "health_check", "lifespan", "websocket_endpoint"]
