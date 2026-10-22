"""backend package root."""
import sys
from pathlib import Path

# Ensure backend root is on sys.path for direct imports
_backend_dir = str(Path(__file__).resolve().parent)
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)
