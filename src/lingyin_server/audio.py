from __future__ import annotations

import json
import math
import subprocess
import uuid
from pathlib import Path
from typing import Iterable

from .models import AcousticAnalysis, AcousticEvent


class AudioError(RuntimeError):
    pass


def _run(command: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"missing audio dependency: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AudioError("audio preprocessing timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "ffmpeg failed").strip()
        raise AudioError(detail[-500:]) from exc


def probe_duration(path: Path, timeout: float = 15.0) -> float | None:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        timeout,
    )
    try:
        value = json.loads(result.stdout)["format"]["duration"]
        duration = float(value)
        return duration if math.isfinite(duration) else None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def normalize_audio(source: Path, work_dir: Path, max_seconds: int) -> Path:
    duration = probe_duration(source)
    if duration is not None and duration > max_seconds + 0.25:
        raise AudioError(f"audio is {duration:.1f}s; limit is {max_seconds}s")

    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / f"{uuid.uuid4().hex}.wav"
    try:
        _run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(target),
            ],
            timeout=max(30.0, max_seconds * 2.0),
        )
        import soundfile as sf

        info = sf.info(target)
        if info.duration <= 0.05:
            raise AudioError("audio is empty or unreadable")
        if info.duration > max_seconds + 0.25:
            raise AudioError(f"audio is {info.duration:.1f}s; limit is {max_seconds}s")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


def _finite_median(values) -> float | None:
    import numpy as np

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    return float(np.median(finite)) if finite.size else None


def _mad(values, center: float | None = None) -> float:
    import numpy as np

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if not finite.size:
        return 0.0
    pivot = float(np.median(finite)) if center is None else center
    return float(np.median(np.abs(finite - pivot)))


def _ranges(mask, times, minimum_frames: int = 2) -> Iterable[tuple[int, int]]:
    start: int | None = None
    for index, active in enumerate(mask):
        if bool(active) and start is None:
            start = index
        if start is not None and (not bool(active) or index == len(mask) - 1):
            end = index if bool(active) and index == len(mask) - 1 else index - 1
            if end - start + 1 >= minimum_frames:
                yield start, end
            start = None


def _event_groups(values, times, label_high: str, label_low: str | None = None):
    import numpy as np

    values = np.asarray(values, dtype=float)
    finite = np.isfinite(values)
    if finite.sum() < 4:
        return []
    center = float(np.median(values[finite]))
    scale = max(1.4826 * _mad(values[finite], center), 1e-6)
    z = (values - center) / scale
    output: list[AcousticEvent] = []
    for start, end in _ranges(finite & (z >= 2.5), times):
        output.append(
            AcousticEvent(
                start=round(float(times[start]), 2),
                end=round(float(times[end] + 0.1), 2),
                observation=label_high,
                strength=round(float(np.nanmax(z[start : end + 1])), 2),
            )
        )
    if label_low:
        for start, end in _ranges(finite & (z <= -2.5), times):
            output.append(
                AcousticEvent(
                    start=round(float(times[start]), 2),
                    end=round(float(times[end] + 0.1), 2),
                    observation=label_low,
                    strength=round(float(abs(np.nanmin(z[start : end + 1]))), 2),
                )
            )
    return output


def _compare_baseline(summary: dict[str, float | str | None], baseline: dict | None):
    if not baseline:
        return None
    output: dict[str, float] = {}
    for key, stats in baseline.get("features", {}).items():
        current = summary.get(key)
        if not isinstance(current, (int, float)) or current is None:
            continue
        center = float(stats.get("median", 0.0))
        scale = max(float(stats.get("scaled_mad", 0.0)), float(stats.get("floor", 1e-6)))
        output[key] = round((float(current) - center) / scale, 2)
    return output or None


def extract_acoustics(path: Path, baseline: dict | None = None) -> AcousticAnalysis:
    # Heavy numerical imports stay inside the worker, keeping idle memory low.
    import librosa
    import numpy as np
    import soundfile as sf

    y, sample_rate = sf.read(path, dtype="float32", always_2d=False)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    if sample_rate != 16000:
        y = librosa.resample(y, orig_sr=sample_rate, target_sr=16000)
        sample_rate = 16000
    duration = len(y) / sample_rate

    hop_length = 1600  # 100 ms
    frame_length = 3200
    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(np.maximum(rms, 1e-8), ref=1.0, top_db=80.0)
    centroid = librosa.feature.spectral_centroid(
        y=y, sr=sample_rate, n_fft=frame_length, hop_length=hop_length
    )[0]
    onset = librosa.onset.onset_strength(y=y, sr=sample_rate, hop_length=hop_length)
    f0 = librosa.yin(
        y,
        fmin=65,
        fmax=450,
        sr=sample_rate,
        frame_length=frame_length,
        hop_length=hop_length,
    )

    count = min(len(rms_db), len(centroid), len(onset), len(f0))
    rms_db = rms_db[:count]
    centroid = centroid[:count]
    onset = onset[:count]
    f0 = f0[:count]
    times = np.arange(count, dtype=float) * (hop_length / sample_rate)

    active_threshold = max(-52.0, float(np.nanmedian(rms_db)) - 18.0)
    active = rms_db > active_threshold
    f0 = f0.astype(float)
    f0[~active] = np.nan

    voiced_f0 = f0[np.isfinite(f0)]
    onset_times = librosa.onset.onset_detect(
        onset_envelope=onset,
        sr=sample_rate,
        hop_length=hop_length,
        units="time",
        backtrack=False,
    )
    summary: dict[str, float | str | None] = {
        "median_pitch_hz": round(_finite_median(voiced_f0) or 0.0, 2) if voiced_f0.size else None,
        "pitch_range_hz": round(float(np.percentile(voiced_f0, 90) - np.percentile(voiced_f0, 10)), 2)
        if voiced_f0.size >= 4
        else None,
        "median_energy_db": round(_finite_median(rms_db) or -80.0, 2),
        "energy_range_db": round(float(np.percentile(rms_db, 90) - np.percentile(rms_db, 10)), 2),
        "median_brightness_hz": round(_finite_median(centroid) or 0.0, 2),
        "median_onset_strength": round(_finite_median(onset) or 0.0, 3),
        "pause_ratio": round(float(1.0 - np.mean(active)), 3),
        "sound_edges_per_minute": round(float(len(onset_times) / max(duration, 0.1) * 60.0), 1),
    }

    events: list[AcousticEvent] = []
    events.extend(_event_groups(rms_db, times, "声音能量明显升高", "声音能量明显收低"))
    events.extend(_event_groups(f0, times, "音高明显上扬", "音高明显下沉"))
    events.extend(_event_groups(centroid, times, "声音的高频亮度明显增加"))
    events.extend(_event_groups(onset, times, "发声边缘突然变得清晰"))

    silence = ~active
    for start, end in _ranges(silence, times, minimum_frames=4):
        events.append(
            AcousticEvent(
                start=round(float(times[start]), 2),
                end=round(min(duration, float(times[end] + 0.1)), 2),
                observation="出现一段可感知的停顿",
                strength=round(float(end - start + 1) / 4.0, 2),
            )
        )

    # Keep the most informative events, then restore timeline order.
    events = sorted(events, key=lambda item: item.strength, reverse=True)[:12]
    events.sort(key=lambda item: item.start)
    return AcousticAnalysis(
        duration_seconds=round(duration, 2),
        summary=summary,
        events=events,
        baseline_comparison=_compare_baseline(summary, baseline),
    )

