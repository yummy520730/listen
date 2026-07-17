from pathlib import Path

import httpx

from lingyin_server.clients import ProviderClients, transcript_from_elevenlabs
from lingyin_server.config import Settings


def test_elevenlabs_words_become_phrase_segments():
    transcript = transcript_from_elevenlabs(
        {
            "text": "你好。再见",
            "words": [
                {"text": "你", "start": 0.1, "end": 0.3, "type": "word"},
                {"text": "好", "start": 0.3, "end": 0.6, "type": "word"},
                {"text": "。", "start": 0.6, "end": 0.7, "type": "word"},
                {"text": "再", "start": 1.8, "end": 2.0, "type": "word"},
                {"text": "见", "start": 2.0, "end": 2.3, "type": "word"},
            ],
        }
    )

    assert transcript.text == "你好。再见"
    assert [(item.start, item.end, item.text) for item in transcript.segments] == [
        (0.1, 0.7, "你好。"),
        (1.8, 2.3, "再见"),
    ]


def test_elevenlabs_provider_defaults(monkeypatch):
    monkeypatch.setenv("ASR_PROVIDER", "elevenlabs")
    monkeypatch.delenv("ASR_BASE_URL", raising=False)
    monkeypatch.delenv("ASR_MODEL", raising=False)

    settings = Settings.from_env()

    assert settings.asr_base_url == "https://api.elevenlabs.io/v1"
    assert settings.asr_model == "scribe_v2"


async def test_elevenlabs_transcription_request(tmp_path: Path):
    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        assert str(request.url) == "https://api.elevenlabs.io/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "test-key"
        assert b'name="model_id"' in body and b"scribe_v2" in body
        assert b'name="language_code"' in body and b"zh" in body
        return httpx.Response(
            200,
            json={
                "text": "测试",
                "words": [{"text": "测试", "start": 0.0, "end": 0.5, "type": "word"}],
            },
        )

    providers = ProviderClients(
        asr_provider="elevenlabs",
        asr_base_url="https://api.elevenlabs.io/v1",
        asr_api_key="test-key",
        asr_model="scribe_v2",
        asr_language_code="zh",
        llm_base_url="https://example.com/v1",
        llm_api_key="",
        llm_model="",
        timeout=5,
    )
    await providers.elevenlabs.aclose()
    providers.elevenlabs = httpx.AsyncClient(
        base_url="https://api.elevenlabs.io/v1",
        headers={"xi-api-key": "test-key"},
        transport=httpx.MockTransport(handler),
    )
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"RIFF-test")
    try:
        transcript = await providers.transcribe(audio)
        assert transcript.text == "测试"
    finally:
        await providers.close()
