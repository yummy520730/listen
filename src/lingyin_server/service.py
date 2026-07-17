from __future__ import annotations

import asyncio
from pathlib import Path

from .audio import extract_acoustics, normalize_audio
from .baseline import BaselineStore
from .clients import ProviderClients, build_result
from .config import Settings
from .download import download_audio
from .storage import Store


class AnalysisService:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        baseline: BaselineStore,
        providers: ProviderClients,
    ):
        self.settings = settings
        self.store = store
        self.baseline = baseline
        self.providers = providers
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.workers: list[asyncio.Task] = []

    async def start(self) -> None:
        self.store.cleanup()
        for job_id in self.store.recover_pending():
            await self.queue.put(job_id)
        self.workers = [
            asyncio.create_task(self._worker(), name=f"lingyin-worker-{index}")
            for index in range(self.settings.max_concurrency)
        ]

    async def close(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        await self.providers.close()

    async def submit(self, *, upload_id: str = "", audio_url: str = "", context: str = "") -> dict:
        upload_id = upload_id.strip()
        audio_url = audio_url.strip()
        if bool(upload_id) == bool(audio_url):
            raise ValueError("provide exactly one of upload_id or audio_url")
        if upload_id and not self.store.get_upload(upload_id):
            raise ValueError("upload_id does not exist or has expired")
        kind, value = ("upload", upload_id) if upload_id else ("url", audio_url)
        job_id = self.store.create_job(kind, value, context)
        await self.queue.put(job_id)
        return {"job_id": job_id, "status": "queued", "next": "Call lingyin_wait or lingyin_result."}

    async def wait(self, job_id: str, timeout_seconds: float = 45) -> dict:
        timeout_seconds = max(0.0, min(float(timeout_seconds), 50.0))
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            job = self.store.get_job(job_id)
            if not job:
                raise ValueError("job_id was not found")
            if job["status"] in {"done", "error"}:
                return job
            if asyncio.get_running_loop().time() >= deadline:
                return job
            await asyncio.sleep(0.5)

    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._process(job_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.store.set_error(job_id, str(exc) or exc.__class__.__name__)
            finally:
                self.queue.task_done()

    async def _process(self, job_id: str) -> None:
        source = self.store.job_source(job_id)
        if not source or source["status"] not in {"queued", "running"}:
            return
        self.store.set_status(job_id, "running")
        original: Path | None = None
        normalized: Path | None = None
        upload_id: str | None = None
        downloaded = False
        try:
            if source["source_kind"] == "upload":
                upload_id = source["source_value"]
                upload = self.store.get_upload(upload_id)
                if not upload:
                    raise ValueError("uploaded audio expired before processing")
                original = Path(upload["path"])
            else:
                original = await download_audio(
                    source["source_value"],
                    self.settings.data_dir / "work",
                    self.settings.max_audio_bytes,
                    self.settings.download_timeout_seconds,
                )
                downloaded = True

            normalized = await asyncio.to_thread(
                normalize_audio,
                original,
                self.settings.data_dir / "work",
                self.settings.max_audio_seconds,
            )
            baseline = self.baseline.read()
            transcription_task = asyncio.create_task(self.providers.transcribe(normalized))
            acoustics_task = asyncio.to_thread(extract_acoustics, normalized, baseline)
            transcript, acoustics = await asyncio.gather(transcription_task, acoustics_task)
            description, fallback_used = await self.providers.describe(
                transcript, acoustics, source.get("context", "")
            )
            result = build_result(description, fallback_used, transcript, acoustics)
            self.store.set_result(job_id, result.to_dict())
        finally:
            if normalized:
                normalized.unlink(missing_ok=True)
            if downloaded and original:
                original.unlink(missing_ok=True)
            if upload_id:
                self.store.delete_upload(upload_id)

