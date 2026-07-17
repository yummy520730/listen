from pathlib import Path

from lingyin_server.baseline import BaselineStore
from lingyin_server.config import Settings
from lingyin_server.models import AcousticAnalysis, Transcript
from lingyin_server.service import AnalysisService
from lingyin_server.storage import Store


class FakeProviders:
    async def transcribe(self, path: Path) -> Transcript:
        return Transcript(text="测试声音")

    async def describe(self, transcript, acoustics, context=""):
        return "听见一段测试声音。", False

    async def close(self):
        return None


async def test_service_processes_one_upload(tmp_path: Path, monkeypatch):
    settings = Settings(
        access_token="secret",
        public_base_url="",
        data_dir=tmp_path,
        max_audio_bytes=1024 * 1024,
        max_audio_seconds=60,
        upload_ttl_hours=1,
        job_ttl_days=1,
        download_timeout_seconds=5,
        provider_timeout_seconds=5,
        max_concurrency=1,
        asr_base_url="https://example.com/v1",
        asr_api_key="key",
        asr_model="asr",
        llm_base_url="https://example.com/v1",
        llm_api_key="",
        llm_model="",
        port=8080,
    )
    settings.prepare_directories()
    store = Store(tmp_path / "db.sqlite3", 1, 1)
    baseline = BaselineStore(tmp_path / "baseline" / "baseline.json")
    service = AnalysisService(settings, store, baseline, FakeProviders())

    audio = tmp_path / "uploads" / "test.audio"
    audio.write_bytes(b"not-real-audio-because-normalization-is-mocked")
    upload_id = store.add_upload(audio, "test.wav", audio.stat().st_size)

    monkeypatch.setattr("lingyin_server.service.normalize_audio", lambda source, *_: source)
    monkeypatch.setattr(
        "lingyin_server.service.extract_acoustics",
        lambda *_: AcousticAnalysis(duration_seconds=1.0, summary={}, events=[]),
    )

    await service.start()
    try:
        submitted = await service.submit(upload_id=upload_id)
        result = await service.wait(submitted["job_id"], timeout_seconds=3)
        assert result["status"] == "done"
        assert result["result"]["description"] == "听见一段测试声音。"
        assert not audio.exists()
    finally:
        await service.close()

