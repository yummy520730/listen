from __future__ import annotations

import asyncio
import contextlib
import uuid
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from .audio import extract_acoustics, normalize_audio
from .auth import TokenAuthMiddleware
from .baseline import BaselineStore
from .clients import ProviderClients
from .config import Settings
from .oauth import LingYinOAuthProvider, OAuthLoginError, OAUTH_SCOPES, render_oauth_login
from .service import AnalysisService
from .storage import Store


settings = Settings.from_env()
settings.prepare_directories()
store = Store(settings.data_dir / "lingyin.sqlite3", settings.upload_ttl_hours, settings.job_ttl_days)
baseline_store = BaselineStore(settings.data_dir / "baseline" / "baseline.json")
providers = ProviderClients(
    asr_provider=settings.asr_provider,
    asr_base_url=settings.asr_base_url,
    asr_api_key=settings.asr_api_key,
    asr_model=settings.asr_model,
    asr_language_code=settings.asr_language_code,
    llm_base_url=settings.llm_base_url,
    llm_api_key=settings.llm_api_key,
    llm_model=settings.llm_model,
    timeout=settings.provider_timeout_seconds,
)
service = AnalysisService(settings, store, baseline_store, providers)
OAUTH_PAGE_CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; "
    "form-action 'self' https://claude.ai https://claude.com; "
    "frame-ancestors 'none'; base-uri 'none'"
)
oauth_provider = None
oauth_settings = None
if settings.mcp_auth_mode == "oauth":
    oauth_provider = LingYinOAuthProvider(
        settings.data_dir / "lingyin.sqlite3",
        issuer_url=settings.server_base_url,
        resource_url=settings.oauth_resource_url,
        owner_password=settings.access_token,
    )
    oauth_settings = AuthSettings(
        issuer_url=settings.server_base_url,
        service_documentation_url=settings.server_base_url,
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=OAUTH_SCOPES,
            default_scopes=["lingyin"],
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=["lingyin"],
        resource_server_url=settings.oauth_resource_url,
    )

mcp = FastMCP(
    "LingYin",
    stateless_http=True,
    json_response=True,
    auth_server_provider=oauth_provider,
    auth=oauth_settings,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[urlparse(settings.server_base_url).netloc, "127.0.0.1:*", "localhost:*"],
        allowed_origins=[
            settings.server_base_url,
            "https://claude.ai",
            "https://claude.com",
            "http://127.0.0.1:*",
            "http://localhost:*",
        ],
    ),
)
mcp.settings.streamable_http_path = "/mcp"


if oauth_provider is not None:

    @mcp.custom_route("/oauth/login", methods=["GET", "POST"])
    async def oauth_login(request: Request):
        if request.method == "GET":
            request_id = request.query_params.get("request", "")
            pending = oauth_provider.get_pending_login(request_id)
            return HTMLResponse(
                render_oauth_login(request_id, pending),
                status_code=200 if pending else 410,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": OAUTH_PAGE_CSP,
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                },
            )

        form = await request.form(max_fields=4)
        request_id = str(form.get("request", ""))
        password = str(form.get("password", ""))
        try:
            return RedirectResponse(
                oauth_provider.complete_authorization(request_id, password),
                status_code=303,
                headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
            )
        except OAuthLoginError as exc:
            pending = oauth_provider.get_pending_login(request_id)
            return HTMLResponse(
                render_oauth_login(request_id, pending, str(exc)),
                status_code=401 if pending else 410,
                headers={
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": OAUTH_PAGE_CSP,
                    "X-Frame-Options": "DENY",
                    "Referrer-Policy": "no-referrer",
                },
            )


@mcp.tool()
async def lingyin_submit(upload_id: str = "", audio_url: str = "", context: str = "") -> dict:
    """Submit one voice recording for LingYin to hear.

    Provide exactly one input. Use upload_id after the user uploads audio on the LingYin web page.
    Use audio_url only for a public direct http(s) audio URL. A local path or a Claude attachment
    path is not accessible to this cloud server. Returns quickly with a job_id.
    """
    return await service.submit(upload_id=upload_id, audio_url=audio_url, context=context)


@mcp.tool()
async def lingyin_wait(job_id: str, timeout_seconds: float = 45) -> dict:
    """Wait up to 50 seconds for a LingYin job. Call again if it remains queued/running.

    When a completed result has llm_fallback_used=true, use its transcript, acoustic_summary,
    acoustic_events, and baseline_comparison to write the final natural description yourself.
    Describe audible shape and change without asserting emotion, personality, deception, or diagnosis.
    """
    return await service.wait(job_id, timeout_seconds)


@mcp.tool()
async def lingyin_result(job_id: str) -> dict:
    """Read the current status or completed hearing result for a LingYin job."""
    job = store.get_job(job_id)
    if not job:
        raise ValueError("job_id was not found")
    return job


@mcp.tool()
async def lingyin_info() -> dict:
    """Show LingYin readiness, upload-page location, limits, and personal-baseline status."""
    baseline = baseline_store.read()
    return {
        "ready": settings.providers_ready,
        "asr_provider": settings.asr_provider,
        "server_prose_model": settings.llm_ready,
        "authentication": "oauth2-pkce" if settings.mcp_auth_mode == "oauth" else "none",
        "upload_page": settings.public_base_url or "Open this server's root URL in a browser.",
        "max_audio_seconds": settings.max_audio_seconds,
        "max_audio_mb": round(settings.max_audio_bytes / 1024 / 1024),
        "personal_baseline": {
            "configured": bool(baseline),
            "sample_count": baseline.get("sample_count", 0) if baseline else 0,
            "created_at": baseline.get("created_at") if baseline else None,
        },
    }


async def homepage(_: Request) -> HTMLResponse:
    path = Path(__file__).parent / "static" / "index.html"
    return HTMLResponse(path.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})


async def health(_: Request) -> JSONResponse:
    baseline = baseline_store.read()
    return JSONResponse(
        {
            "status": "ok",
            "providers_configured": settings.providers_ready,
            "asr_provider": settings.asr_provider,
            "server_prose_model_configured": settings.llm_ready,
            "access_token_configured": bool(settings.access_token),
            "mcp_auth_mode": settings.mcp_auth_mode,
            "oauth_configured": bool(
                settings.mcp_auth_mode == "oauth" and settings.access_token and settings.public_base_url
            ),
            "baseline_samples": baseline.get("sample_count", 0) if baseline else 0,
            "queued_jobs": service.queue.qsize(),
        },
        headers={"Cache-Control": "no-store"},
    )


async def _save_upload(file: UploadFile) -> str:
    if not file.filename:
        raise ValueError("audio file has no filename")
    target = settings.data_dir / "uploads" / f"{uuid.uuid4().hex}.audio"
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(64 * 1024):
                total += len(chunk)
                if total > settings.max_audio_bytes:
                    raise ValueError("audio exceeds the configured size limit")
                output.write(chunk)
        if total == 0:
            raise ValueError("audio file is empty")
        return store.add_upload(target, Path(file.filename).name[:200], total)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


async def upload(request: Request) -> JSONResponse:
    try:
        form = await request.form(max_files=1, max_fields=5, max_part_size=settings.max_audio_bytes)
        file = form.get("audio")
        if not isinstance(file, UploadFile):
            raise ValueError("multipart field 'audio' is required")
        upload_id = await _save_upload(file)
        return JSONResponse({"upload_id": upload_id, "expires_in_hours": settings.upload_ttl_hours})
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def analyze(request: Request) -> JSONResponse:
    try:
        form = await request.form(max_files=1, max_fields=5, max_part_size=settings.max_audio_bytes)
        file = form.get("audio")
        if not isinstance(file, UploadFile):
            raise ValueError("multipart field 'audio' is required")
        upload_id = await _save_upload(file)
        result = await service.submit(upload_id=upload_id, context=str(form.get("context", "")))
        return JSONResponse(result, status_code=202)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def job_result(request: Request) -> JSONResponse:
    job = store.get_job(request.path_params["job_id"])
    if not job:
        return JSONResponse({"error": "job_id was not found"}, status_code=404)
    return JSONResponse(job)


async def baseline_status(_: Request) -> JSONResponse:
    baseline = baseline_store.read()
    return JSONResponse(
        {
            "configured": bool(baseline),
            "sample_count": baseline.get("sample_count", 0) if baseline else 0,
            "created_at": baseline.get("created_at") if baseline else None,
        }
    )


async def calibrate(request: Request) -> JSONResponse:
    upload_ids: list[str] = []
    normalized_paths: list[Path] = []
    try:
        form = await request.form(max_files=8, max_fields=3, max_part_size=settings.max_audio_bytes)
        files = [value for key, value in form.multi_items() if key == "audio" and isinstance(value, UploadFile)]
        if not 3 <= len(files) <= 8:
            raise ValueError("choose 3 to 8 ordinary voice recordings for calibration")
        for file in files:
            upload_ids.append(await _save_upload(file))

        summaries = []
        for upload_id in upload_ids:
            record = store.get_upload(upload_id)
            if not record:
                raise ValueError("a calibration upload expired")
            normalized = await asyncio.to_thread(
                normalize_audio,
                Path(record["path"]),
                settings.data_dir / "work",
                settings.max_audio_seconds,
            )
            normalized_paths.append(normalized)
            analysis = await asyncio.to_thread(extract_acoustics, normalized, None)
            summaries.append(analysis.summary)
        baseline = await asyncio.to_thread(baseline_store.write, summaries)
        return JSONResponse(
            {
                "configured": True,
                "sample_count": baseline["sample_count"],
                "created_at": baseline["created_at"],
            }
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        for path in normalized_paths:
            path.unlink(missing_ok=True)
        for upload_id in upload_ids:
            store.delete_upload(upload_id)


@contextlib.asynccontextmanager
async def lifespan(_: Starlette):
    await service.start()
    async with mcp.session_manager.run():
        yield
    await service.close()


mcp_http_app = mcp.streamable_http_app()
routes = [
    Route("/", homepage, methods=["GET"]),
    Route("/healthz", health, methods=["GET"]),
    Route("/api/upload", upload, methods=["POST"]),
    Route("/api/analyze", analyze, methods=["POST"]),
    Route("/api/calibrate", calibrate, methods=["POST"]),
    Route("/api/baseline", baseline_status, methods=["GET"]),
    Route("/api/jobs/{job_id}", job_result, methods=["GET"]),
    Mount("/", app=mcp_http_app),
]

starlette_app = Starlette(routes=routes, lifespan=lifespan)
app = TokenAuthMiddleware(starlette_app, settings.access_token)
