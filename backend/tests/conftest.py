"""Settings shared by every test: recorded interviewer lines go to a temporary folder, never data/."""

from __future__ import annotations

import pytest

from backend.pipeline import fixed_audio


@pytest.fixture(autouse=True)
def recordings_in_a_temporary_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(fixed_audio, "CACHE_DIR", tmp_path / "tts_cache")
