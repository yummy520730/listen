from __future__ import annotations

import asyncio
import ipaddress
import socket
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


class DownloadError(RuntimeError):
    pass


async def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DownloadError("audio_url must be a public http(s) URL")
    if parsed.username or parsed.password:
        raise DownloadError("credentials in audio_url are not allowed")
    try:
        records = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: socket.getaddrinfo(
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            ),
        )
    except socket.gaierror as exc:
        raise DownloadError("audio_url hostname could not be resolved") from exc
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            raise DownloadError("audio_url cannot point to a private or local address")


async def download_audio(url: str, target_dir: Path, max_bytes: int, timeout: float) -> Path:
    current = url
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"remote-{uuid.uuid4().hex}.audio"
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(4):
                await _validate_public_url(current)
                async with client.stream("GET", current, headers={"Accept": "audio/*,application/octet-stream"}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise DownloadError("audio_url redirect has no location")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    declared = int(response.headers.get("content-length", "0") or 0)
                    if declared > max_bytes:
                        raise DownloadError("remote audio exceeds the configured size limit")
                    total = 0
                    with target.open("wb") as output:
                        async for chunk in response.aiter_bytes(64 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise DownloadError("remote audio exceeds the configured size limit")
                            output.write(chunk)
                    if total == 0:
                        raise DownloadError("remote audio is empty")
                    return target
            raise DownloadError("audio_url redirected too many times")
    except httpx.HTTPError as exc:
        raise DownloadError(f"could not download audio: {exc}") from exc
    except Exception:
        target.unlink(missing_ok=True)
        raise
