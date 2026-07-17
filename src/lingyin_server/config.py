from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    value = default if raw is None or raw == "" else int(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _float(name: str, default: float, minimum: float = 0.1) -> float:
    raw = os.getenv(name)
    value = default if raw is None or raw == "" else float(raw)
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    access_token: str
    public_base_url: str
    data_dir: Path
    max_audio_bytes: int
    max_audio_seconds: int
    upload_ttl_hours: int
    job_ttl_days: int
    download_timeout_seconds: float
    provider_timeout_seconds: float
    max_concurrency: int
    asr_base_url: str
    asr_api_key: str
    asr_model: str
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    port: int

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("LINGYIN_DATA_DIR", "/data")).expanduser()
        return cls(
            access_token=os.getenv("LINGYIN_ACCESS_TOKEN", "").strip(),
            public_base_url=os.getenv("LINGYIN_PUBLIC_BASE_URL", "").strip().rstrip("/"),
            data_dir=data_dir,
            max_audio_bytes=_int("LINGYIN_MAX_AUDIO_MB", 25) * 1024 * 1024,
            max_audio_seconds=_int("LINGYIN_MAX_AUDIO_SECONDS", 60),
            upload_ttl_hours=_int("LINGYIN_UPLOAD_TTL_HOURS", 24),
            job_ttl_days=_int("LINGYIN_JOB_TTL_DAYS", 7),
            download_timeout_seconds=_float("LINGYIN_DOWNLOAD_TIMEOUT_SECONDS", 30),
            provider_timeout_seconds=_float("LINGYIN_PROVIDER_TIMEOUT_SECONDS", 120),
            max_concurrency=_int("LINGYIN_MAX_CONCURRENCY", 1),
            asr_base_url=os.getenv("ASR_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            asr_api_key=os.getenv("ASR_API_KEY", "").strip(),
            asr_model=os.getenv("ASR_MODEL", "gpt-4o-mini-transcribe").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
            llm_model=os.getenv("LLM_MODEL", "gpt-4.1-mini").strip(),
            port=_int("PORT", 8080),
        )

    def prepare_directories(self) -> None:
        for name in ("uploads", "work", "baseline"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)

    @property
    def providers_ready(self) -> bool:
        return bool(self.asr_api_key and self.asr_model)

    @property
    def llm_ready(self) -> bool:
        return bool(self.llm_api_key and self.llm_model)
