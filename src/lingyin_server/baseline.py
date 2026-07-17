from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Iterable


FEATURE_FLOORS = {
    "median_pitch_hz": 8.0,
    "pitch_range_hz": 10.0,
    "median_energy_db": 2.0,
    "energy_range_db": 2.0,
    "median_brightness_hz": 120.0,
    "median_onset_strength": 0.08,
    "pause_ratio": 0.05,
    "sound_edges_per_minute": 5.0,
}


class BaselineStore:
    def __init__(self, path: Path):
        self.path = path
        self._lock = Lock()

    def read(self) -> dict | None:
        with self._lock:
            if not self.path.exists():
                return None
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None

    def write(self, summaries: Iterable[dict[str, float | str | None]]) -> dict:
        import numpy as np

        rows = list(summaries)
        if len(rows) < 3:
            raise ValueError("at least 3 baseline recordings are required")
        features: dict[str, dict[str, float]] = {}
        for key, floor in FEATURE_FLOORS.items():
            values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
            if len(values) < max(3, len(rows) // 2):
                continue
            center = float(np.median(values))
            mad = float(np.median(np.abs(np.asarray(values) - center)))
            features[key] = {
                "median": round(center, 4),
                "scaled_mad": round(1.4826 * mad, 4),
                "floor": floor,
            }
        payload = {
            "version": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "sample_count": len(rows),
            "features": features,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        with self._lock:
            temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)
        return payload

