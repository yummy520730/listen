import math
from pathlib import Path

import numpy as np
import soundfile as sf

from lingyin_server.audio import extract_acoustics


def test_extract_acoustics_from_synthetic_voice(tmp_path: Path):
    sample_rate = 16000
    first = 0.15 * np.sin(2 * math.pi * 120 * np.arange(sample_rate) / sample_rate)
    silence = np.zeros(sample_rate // 2)
    second = 0.35 * np.sin(2 * math.pi * 220 * np.arange(sample_rate) / sample_rate)
    audio = np.concatenate([first, silence, second]).astype("float32")
    path = tmp_path / "sample.wav"
    sf.write(path, audio, sample_rate)

    result = extract_acoustics(path)
    assert 2.45 <= result.duration_seconds <= 2.55
    assert result.summary["median_pitch_hz"] is not None
    assert result.summary["pause_ratio"] > 0.05
    assert any("停顿" in event.observation for event in result.events)

