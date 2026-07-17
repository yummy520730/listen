from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class Transcript:
    text: str
    segments: list[TranscriptSegment] = field(default_factory=list)


@dataclass(slots=True)
class AcousticEvent:
    start: float
    end: float
    observation: str
    strength: float


@dataclass(slots=True)
class AcousticAnalysis:
    duration_seconds: float
    summary: dict[str, float | str | None]
    events: list[AcousticEvent]
    baseline_comparison: dict[str, float] | None = None


@dataclass(slots=True)
class HearingResult:
    description: str
    transcript: str
    transcript_segments: list[TranscriptSegment]
    duration_seconds: float
    acoustic_summary: dict[str, float | str | None]
    acoustic_events: list[AcousticEvent]
    baseline_comparison: dict[str, float] | None
    llm_fallback_used: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

