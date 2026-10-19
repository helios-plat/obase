from pathlib import Path
from unittest.mock import patch
import pytest

from obase.kokoro_runtime import KokoroRuntime, KokoroRuntimeError, write_audio_file


def test_is_loaded_false_initially():
    rt = KokoroRuntime()
    assert rt.is_loaded() is False


def test_load_missing_raises():
    rt = KokoroRuntime()
    with patch.dict("sys.modules", {"kokoro": None}):
        with pytest.raises(KokoroRuntimeError):
            rt._load()


def test_write_audio_file(tmp_path):
    out = tmp_path / "a.wav"
    res = write_audio_file([0.1, -0.1, 0.5], out)
    assert res == out
    assert out.exists() and out.stat().st_size > 0
