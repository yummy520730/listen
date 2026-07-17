from pathlib import Path

from lingyin_server.baseline import BaselineStore


def test_baseline_uses_robust_center(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    summaries = [
        {"median_pitch_hz": 100.0, "median_energy_db": -22.0, "pause_ratio": 0.20},
        {"median_pitch_hz": 102.0, "median_energy_db": -21.0, "pause_ratio": 0.22},
        {"median_pitch_hz": 101.0, "median_energy_db": -20.0, "pause_ratio": 0.19},
        {"median_pitch_hz": 350.0, "median_energy_db": -5.0, "pause_ratio": 0.90},
    ]
    result = store.write(summaries)
    assert result["sample_count"] == 4
    assert result["features"]["median_pitch_hz"]["median"] == 101.5
    assert store.read() == result


def test_baseline_requires_three_samples(tmp_path: Path):
    store = BaselineStore(tmp_path / "baseline.json")
    try:
        store.write([{}, {}])
    except ValueError as exc:
        assert "at least 3" in str(exc)
    else:
        raise AssertionError("expected ValueError")

