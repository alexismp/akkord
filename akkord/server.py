# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""FastAPI web server for Akkord."""

from __future__ import annotations

from collections.abc import Iterator
import json
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Cookie, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from akkord.activity import DAILY_FILE_LIMIT, ActivityManager
from akkord.config import (
    AVAILABLE_MODELS,
    DEFAULT_API_KEY,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL,
    AkkordConfig,
)
from akkord.drive import DriveConnector, SheetFile
from akkord.firestore_store import FirestoreBackend
from akkord.job_queue import GCSStorageBackend, JobQueueManager
from akkord.oauth import (
    ADMIN_EMAIL,
    ANON_COOKIE_NAME,
    DEFAULT_OAUTH_REDIRECT_URI,
    OAuthManager,
    UserSession,
)
from akkord.pipeline import AkkordPipeline

STATIC_DIR = Path(__file__).parent / "static"
SAMPLES_DIR = Path(__file__).parent.parent / "samples"
OUTPUTS_DIR = (
    Path("/tmp/akkord_outputs") if not Path("outputs").exists() else Path("outputs")
)
UPLOADS_DIR = OUTPUTS_DIR / "_uploads"

SESSION_COOKIE_NAME = "akkord_session"
firestore_backend = FirestoreBackend(OUTPUTS_DIR)
gcs_backend = GCSStorageBackend(OUTPUTS_DIR)
oauth_manager = OAuthManager(OUTPUTS_DIR, firestore_backend=firestore_backend)
activity_manager = ActivityManager(
    OUTPUTS_DIR, gcs_backend=gcs_backend, firestore_backend=firestore_backend
)
activity_manager.start_background_scheduler()
job_queue_manager = JobQueueManager(
    OUTPUTS_DIR, activity_manager=activity_manager, gcs_backend=gcs_backend
)

app = FastAPI(
    title="Akkord — Music Sheet Chord Analyzer & Annotator",
    version="0.3.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


class ScanFolderRequest(BaseModel):
    folder: str = Field(..., min_length=1)
    credentials_path: str | None = None


class ProcessFolderRequest(BaseModel):
    folder: str = Field(..., min_length=1)
    language: str = Field(default=DEFAULT_LANGUAGE)
    model: str = Field(default=DEFAULT_MODEL)
    api_key: str = Field(default=DEFAULT_API_KEY)
    upload_to_drive: bool = Field(default=False)
    selected_ids: list[str] | None = None


def _resolve_redirect_uri(request: Request) -> str:
    """Return the exact registered OAuth 2.0 callback URI."""
    import os

    env_uri = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if env_uri:
        return env_uri
    return DEFAULT_OAUTH_REDIRECT_URI


def _get_current_session(
    akkord_session: str | None = Cookie(default=None),
) -> UserSession | None:
    return oauth_manager.get_session(akkord_session)


def _resolve_request_context(
    request: Request, akkord_session: str | None = None
) -> tuple[UserSession | None, str]:
    """Return (UserSession | None, canonical_owner_id) for the current HTTP request."""
    cookie_sess = akkord_session or request.cookies.get(SESSION_COOKIE_NAME)
    session = oauth_manager.get_session(cookie_sess)
    anon_id = getattr(request.state, "anon_id", None)
    if not anon_id:
        anon_id, _, _ = oauth_manager.get_or_create_anon_id(
            request.cookies.get(ANON_COOKIE_NAME)
        )
    owner_id = oauth_manager.resolve_owner_id(session, anon_id)
    return session, owner_id


@app.middleware("http")
async def attach_owner_and_anon_cookie(request: Request, call_next: Any) -> Response:
    """Ensure every visitor has a signed, isolated anonymous session cookie and resolved owner_id."""
    session = oauth_manager.get_session(request.cookies.get(SESSION_COOKIE_NAME))
    anon_id, signed_anon_cookie, is_new_anon = oauth_manager.get_or_create_anon_id(
        request.cookies.get(ANON_COOKIE_NAME)
    )
    request.state.user_session = session
    request.state.anon_id = anon_id
    request.state.owner_id = oauth_manager.resolve_owner_id(session, anon_id)
    request.state.skip_anon_cookie = False

    response: Response = await call_next(request)
    if is_new_anon and not getattr(request.state, "skip_anon_cookie", False):
        is_https = (
            request.headers.get("x-forwarded-proto") == "https"
            or request.url.scheme == "https"
        )
        response.set_cookie(
            key=ANON_COOKIE_NAME,
            value=signed_anon_cookie,
            httponly=True,
            secure=is_https,
            samesite="lax",
            max_age=60 * 60 * 24 * 30,
        )
    return response


def _forbid_samples_access(folder_or_path: str) -> None:
    """Prevent accessing the test-only samples/ directory from web endpoints."""
    cleaned = folder_or_path.strip()
    try:
        candidate = Path(cleaned).resolve()
        if candidate == SAMPLES_DIR.resolve() or SAMPLES_DIR.resolve() in candidate.parents:
            raise HTTPException(
                status_code=403,
                detail="Access to the test-only samples/ directory is disabled.",
            )
    except HTTPException:
        raise
    except Exception:
        pass


def _resolve_allowed_model(requested_model: str, session: UserSession | None) -> str:
    """Only allow overriding the default Gemini model if the logged-in user is the administrator."""
    cleaned = (requested_model or "").strip()
    if not cleaned:
        return DEFAULT_MODEL
    if session is not None and session.is_admin:
        return cleaned
    return DEFAULT_MODEL


def _sanitize_report_for_session(
    rep_dict: dict[str, Any], session: UserSession | None
) -> dict[str, Any]:
    """Return a copy of the report with token_usage preserved only for the administrator."""
    is_admin = bool(session and session.is_admin)
    out = dict(rep_dict)
    detail = dict(out.get("analysis_detail") or {})
    if is_admin:
        if "token_usage" not in out and detail.get("token_usage"):
            out["token_usage"] = detail["token_usage"]
    else:
        out.pop("token_usage", None)
        if detail:
            detail.pop("token_usage", None)
            out["analysis_detail"] = detail
    return out


@app.get("/", response_class=HTMLResponse, response_model=None)
def index(request: Request) -> HTMLResponse | RedirectResponse:
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or ""
    ).split(",")[0].strip().lower()
    if host == "akkord.cloud.run":
        return RedirectResponse(
            url="https://akkord-2500276981.europe-west1.run.app/",
            status_code=302,
        )
    index_file = STATIC_DIR / "index.html"
    return HTMLResponse(index_file.read_text(encoding="utf-8"))


@app.get("/api/config")
def get_default_config(
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    session, owner_id = _resolve_request_context(request, akkord_session)
    if (
        session
        and session.is_admin
        and not activity_manager._admin_tokens.get("refresh_token")
    ):
        activity_manager.save_admin_oauth_tokens(
            session.email,
            session.access_token,
            session.refresh_token,
            session.client_id,
            session.client_secret,
        )
    is_admin = bool(session and session.is_admin)
    cid, _ = oauth_manager.get_client_credentials()
    return {
        "app_name": "akkord",
        "default_model": DEFAULT_MODEL,
        "available_models": list(AVAILABLE_MODELS) if is_admin else [DEFAULT_MODEL],
        "default_language": DEFAULT_LANGUAGE,
        "supported_languages": [
            {"code": "fr", "label": "Français (FR)"},
            {"code": "en", "label": "English (EN)"},
        ],
        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
        "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
        "auth": {
            "authenticated": session is not None,
            "email": session.email if session else "",
            "name": session.name if session else "",
            "picture": session.picture if session else "",
            "is_admin": is_admin,
            "admin_email": ADMIN_EMAIL,
            "oauth_configured": oauth_manager.is_configured(),
            "oauth_client_id_preview": (cid[:18] + "…") if len(cid) > 18 else cid,
            "redirect_uri": _resolve_redirect_uri(request),
        },
    }


@app.get("/api/auth/status")
def auth_status(
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    session = oauth_manager.get_session(akkord_session)
    return {
        "authenticated": session is not None,
        "email": session.email if session else "",
        "name": session.name if session else "",
        "picture": session.picture if session else "",
        "is_admin": bool(session and session.is_admin),
        "oauth_configured": oauth_manager.is_configured(),
        "redirect_uri": _resolve_redirect_uri(request),
    }


@app.get("/auth/login")
def oauth_login(request: Request, intent: str = "") -> RedirectResponse:
    """Redirect the user to Google's OAuth 2.0 consent page with Drive & email scopes."""
    redirect_uri = _resolve_redirect_uri(request)
    auth_url = oauth_manager.build_authorization_url(
        redirect_uri=redirect_uri, intent=intent
    )
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/auth/callback")
def oauth_callback(
    request: Request,
    code: str | None = None,
    state: str = "",
    error: str | None = None,
) -> RedirectResponse:
    """Handle Google OAuth 2.0 callback, create session cookie, and redirect to `/`."""
    if error or not code:
        return RedirectResponse(
            url=f"/?oauth_error={error or 'missing_code'}", status_code=302
        )
    intent = oauth_manager.extract_state_intent(state)
    redirect_uri = _resolve_redirect_uri(request)
    try:
        user_session = oauth_manager.exchange_code_for_session(
            code=code,
            state=state,
            fallback_redirect_uri=redirect_uri,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/?oauth_error={str(exc)[:120]}", status_code=302
        )

    # If this browser tab had an anonymous session with in-progress or recent jobs, claim them for the logged-in user
    prior_anon_id = oauth_manager.decode_anon_cookie(
        request.cookies.get(ANON_COOKIE_NAME)
    ) or getattr(request.state, "anon_id", None)
    if prior_anon_id:
        try:
            job_queue_manager.claim_anonymous_jobs(
                f"anon:{prior_anon_id}",
                user_session.email,
                is_admin=user_session.is_admin,
            )
        except Exception:
            pass

    target_url = "/"
    if user_session.is_admin:
        activity_manager.save_admin_oauth_tokens(
            user_session.email,
            user_session.access_token,
            user_session.refresh_token,
            user_session.client_id,
            user_session.client_secret,
        )
        if intent == "send_digest":
            digest_res = activity_manager.send_daily_digest(
                force=True,
                oauth_access_token=user_session.access_token,
                oauth_refresh_token=user_session.refresh_token,
            )
            if digest_res.get("sent"):
                target_url = "/?digest_sent=1"
            else:
                err_msg = (
                    (digest_res.get("errors") or [digest_res.get("reason") or "erreur"])[0]
                )
                target_url = f"/?digest_error={quote(str(err_msg)[:120])}"

    resp = RedirectResponse(url=target_url, status_code=302)
    is_https = (
        request.headers.get("x-forwarded-proto") == "https"
        or request.url.scheme == "https"
    )
    resp.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=user_session.session_id,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=60 * 60 * 24 * 14,
    )
    return resp


@app.post("/api/auth/logout")
def oauth_logout(
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> JSONResponse:
    oauth_manager.delete_session(akkord_session)
    _, fresh_signed_anon, _ = oauth_manager.get_or_create_anon_id(None)
    request.state.skip_anon_cookie = True
    is_https = (
        request.headers.get("x-forwarded-proto") == "https"
        or request.url.scheme == "https"
    )
    resp = JSONResponse({"authenticated": False})
    resp.delete_cookie(SESSION_COOKIE_NAME)
    resp.set_cookie(
        key=ANON_COOKIE_NAME,
        value=fresh_signed_anon,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@app.post("/api/cancel")
def cancel_active_analysis(
    request: Request,
    job_id: str | None = None,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Signal any running PDF analysis, async job, or batch stream owned by the caller to stop immediately."""
    _, owner_id = _resolve_request_context(request, akkord_session)
    activity_manager.request_cancel()
    cancelled_job = job_queue_manager.cancel_job(job_id=job_id, owner_id=owner_id)
    return {
        "cancelled": True,
        "job_id": cancelled_job.job_id if cancelled_job else None,
        "message": "Interruption de l'analyse demandée.",
        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
    }


class ProcessTaskRequest(BaseModel):
    job_id: str = Field(..., min_length=1)
    item_id: str = Field(..., min_length=1)
    force: bool = Field(default=False)


@app.post("/api/jobs/drive", status_code=202)
def create_drive_batch_job(
    request: Request,
    req: ProcessFolderRequest,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Create a decoupled, event-driven batch job for a Google Drive folder (supports 10s or 100s of PDFs)."""
    _forbid_samples_access(req.folder)
    session, owner_id = _resolve_request_context(request, akkord_session)
    oauth_creds = session.to_google_credentials() if session else None
    effective_model = _resolve_allowed_model(req.model, session)

    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=req.api_key.strip() or DEFAULT_API_KEY,
            language=req.language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
            upload_to_drive=req.upload_to_drive,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline = AkkordPipeline(config, oauth_credentials=oauth_creds)
    try:
        sheets = pipeline.scan_folder(req.folder)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.selected_ids:
        allowed = set(req.selected_ids)
        sheets = [s for s in sheets if s.id in allowed or s.name in allowed]

    if not sheets:
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Aucune partition PDF trouvée dans ce dossier. S'il est privé, cliquez d'abord sur « Se connecter avec Google » en haut à droite.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"Aucune partition PDF trouvée dans ce dossier avec le compte {session.email}.",
        )

    oauth_tokens = (
        {
            "access_token": session.access_token,
            "refresh_token": session.refresh_token or "",
            "client_id": session.client_id,
            "client_secret": session.client_secret,
        }
        if session
        else {}
    )
    is_admin = bool(session and session.is_admin)
    job = job_queue_manager.create_batch_job(
        sheets=sheets,
        folder=req.folder,
        language=config.language,
        model=config.model,
        upload_to_drive=req.upload_to_drive,
        user_email=session.email if session else "",
        is_admin=is_admin,
        oauth_tokens=oauth_tokens,
        run_async=True,
        owner_id=owner_id,
    )
    return job_queue_manager.serialize_job_for_client(job, is_admin=is_admin)


@app.post("/api/jobs/upload", status_code=202)
def create_upload_batch_job(
    request: Request,
    files: list[UploadFile] = File(...),
    language: str = Form(DEFAULT_LANGUAGE),
    model: str = Form(DEFAULT_MODEL),
    api_key: str = Form(DEFAULT_API_KEY),
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Create a decoupled, event-driven batch job from uploaded PDF files."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    effective_model = _resolve_allowed_model(model, session)
    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=api_key.strip() or DEFAULT_API_KEY,
            language=language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    saved_sheets: list[SheetFile] = []
    for up in files:
        fname = Path(up.filename or "sheet.pdf").name
        if not fname.lower().endswith(".pdf"):
            continue
        dest = UPLOADS_DIR / fname
        with open(dest, "wb") as out_f:
            shutil.copyfileobj(up.file, out_f)
        saved_sheets.append(
            SheetFile(
                id=fname,
                name=fname,
                source="upload",
                local_path=dest,
            )
        )

    if not saved_sheets:
        raise HTTPException(
            status_code=400,
            detail="Veuillez sélectionner au moins un fichier PDF valide.",
        )

    is_admin = bool(session and session.is_admin)
    job = job_queue_manager.create_batch_job(
        sheets=saved_sheets,
        folder="upload",
        language=config.language,
        model=config.model,
        upload_to_drive=False,
        user_email=session.email if session else "",
        is_admin=is_admin,
        run_async=True,
        owner_id=owner_id,
    )
    return job_queue_manager.serialize_job_for_client(job, is_admin=is_admin)


@app.get("/api/jobs")
def list_recent_jobs(
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Return recent batch jobs and unified history items strictly scoped to the caller's owner_id."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    is_admin = bool(session and session.is_admin)
    jobs = job_queue_manager.list_jobs(limit=10, owner_id=owner_id)
    return {
        "jobs": [
            job_queue_manager.serialize_job_for_client(j, is_admin=is_admin)
            for j in jobs
        ],
        "history_items": job_queue_manager.get_recent_history(
            limit=25, is_admin=is_admin, owner_id=owner_id
        ),
        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
    }


@app.get("/api/jobs/{job_id}")
def get_job_status(
    job_id: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Poll the live progress and per-file status of an asynchronous batch job (strictly owner-checked)."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    is_admin = bool(session and session.is_admin)
    job = job_queue_manager.get_job(job_id, reload_from_gcs=gcs_backend.enabled)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    if not job_queue_manager.job_belongs_to_owner(job, owner_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce traitement est privé et appartient à un autre utilisateur.",
        )
    return job_queue_manager.serialize_job_for_client(job, is_admin=is_admin)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_specific_job(
    job_id: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Cancel an asynchronous batch job and all its queued/deferred items (strictly owner-checked)."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    is_admin = bool(session and session.is_admin)
    existing = job_queue_manager.get_job(job_id, reload_from_gcs=gcs_backend.enabled)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    if not job_queue_manager.job_belongs_to_owner(existing, owner_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce traitement est privé et appartient à un autre utilisateur.",
        )
    job = job_queue_manager.cancel_job(job_id=job_id, owner_id=owner_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    return job_queue_manager.serialize_job_for_client(job, is_admin=is_admin)


@app.get("/api/jobs/{job_id}/download-zip")
def download_job_zip(
    job_id: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> Response:
    """Download a ZIP archive containing all completed annotated PDFs for a batch job (strictly owner-checked)."""
    _, owner_id = _resolve_request_context(request, akkord_session)
    job = job_queue_manager.get_job(job_id, reload_from_gcs=gcs_backend.enabled)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    if not job_queue_manager.job_belongs_to_owner(job, owner_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce lot de partitions appartient à un autre utilisateur.",
        )
    built = job_queue_manager.build_job_zip_bytes(job_id)
    if built is None:
        raise HTTPException(
            status_code=404,
            detail="Aucun fichier PDF annoté disponible pour ce lot.",
        )
    zip_bytes, zip_name = built
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{zip_name}"',
        },
    )


@app.post("/api/internal/tasks/process-file")
def worker_process_single_file(req: ProcessTaskRequest) -> dict[str, Any]:
    """Cloud Tasks HTTP worker endpoint: processes a single PDF file in isolation and frees RAM."""
    return job_queue_manager.process_job_item(req.job_id, req.item_id, force=req.force)


@app.post("/api/internal/tasks/resume-deferred")
def worker_resume_deferred_jobs() -> dict[str, Any]:
    """Cloud Scheduler 00:05 daily hook (also callable by Admin) to resume up to 25 deferred files for the new day."""
    return job_queue_manager.resume_deferred_jobs()


@app.get("/api/admin/usage")
def get_admin_token_usage(
    date: str | None = None,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Return detailed token and monetary cost tracking (strictly admin only)."""
    session = oauth_manager.get_session(akkord_session)
    if not session or not session.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Accès réservé à l'administrateur.",
        )
    return activity_manager.get_usage_summary(date)


@app.post("/api/admin/reset-quota")
def admin_reset_daily_quota(
    date: str | None = None,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Force-reset the administrator's personal 25-file daily quota to 0 (without resetting the 200/day global cap), persisted to Firestore, and auto-resume deferred jobs."""
    session = oauth_manager.get_session(akkord_session)
    if not session or not session.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Accès réservé à l'administrateur.",
        )
    admin_owner_id = f"user:{session.email.lower()}"
    quota_status = activity_manager.reset_daily_quota(date, owner_id=admin_owner_id)
    resumed = job_queue_manager.resume_deferred_jobs(owner_id=admin_owner_id)
    current_quota = activity_manager.get_quota_status(owner_id=admin_owner_id)
    current_quota["previous_used"] = quota_status.get("previous_used", 0)
    return {
        "reset": True,
        "daily_quota": current_quota,
        "previous_used": quota_status.get("previous_used", 0),
        "resumed": resumed,
        "admin_usage": activity_manager.get_usage_summary(date),
    }


@app.get("/api/daily-report/preview")
def preview_daily_report(
    date: str | None = None,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Preview the daily 18:00 summary report (admin only)."""
    session = oauth_manager.get_session(akkord_session)
    if not session or not session.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Accès réservé à l'administrateur.",
        )
    admin_owner_id = f"user:{session.email.lower()}"
    subject, text_body, html_body = activity_manager.build_daily_digest_content(date)
    return {
        "subject": subject,
        "text_body": text_body,
        "html_body": html_body,
        "daily_quota": activity_manager.get_quota_status(owner_id=admin_owner_id),
    }


@app.post("/api/daily-report/send")
def trigger_daily_report(
    date: str | None = None,
    force: bool = False,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Trigger the 18:00 daily summary email if PDFs were analyzed on that day (callable by Cloud Scheduler or Admin)."""
    session = oauth_manager.get_session(akkord_session)
    oauth_token = session.access_token if (session and session.is_admin) else None
    oauth_refresh = session.refresh_token if (session and session.is_admin) else None
    result = activity_manager.send_daily_digest(
        date_str=date,
        force=force,
        oauth_access_token=oauth_token,
        oauth_refresh_token=oauth_refresh,
    )
    return result


@app.get("/api/drive/browse")
def browse_drive(
    folder_id: str = "root",
    q: str = "",
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Browse folders and PDFs inside the authenticated user's Google Drive."""
    session = oauth_manager.get_session(akkord_session)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail="Veuillez vous connecter avec votre compte Google Drive pour parcourir vos dossiers.",
        )
    connector = DriveConnector(oauth_credentials=session.to_google_credentials())
    try:
        return connector.browse_drive_folder(folder_id=folder_id, search_query=q)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/scan-folder")
def scan_folder(
    req: ScanFolderRequest,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    _forbid_samples_access(req.folder)
    session = oauth_manager.get_session(akkord_session)
    oauth_creds = session.to_google_credentials() if session else None

    config = AkkordConfig(
        output_dir=OUTPUTS_DIR,
        google_credentials_path=req.credentials_path,
    )
    pipeline = AkkordPipeline(config, oauth_credentials=oauth_creds)
    try:
        files = pipeline.scan_folder(req.folder)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "folder": req.folder,
        "count": len(files),
        "files": [
            {
                "id": f.id,
                "name": f.name,
                "source": f.source,
                "web_view_link": f.web_view_link,
            }
            for f in files
        ],
    }


@app.post("/api/process")
def process_folder(
    request: Request,
    req: ProcessFolderRequest,
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    _forbid_samples_access(req.folder)
    session, owner_id = _resolve_request_context(request, akkord_session)
    if not activity_manager.can_process_more_today(owner_id=owner_id):
        owner_lim = activity_manager.get_owner_daily_limit(owner_id)
        raise HTTPException(
            status_code=429,
            detail=f"Limite quotidienne atteinte ({owner_lim}/{owner_lim} partitions PDF analysées aujourd'hui). Le quota sera réinitialisé demain.",
        )
    activity_manager.reset_cancel()
    oauth_creds = session.to_google_credentials() if session else None
    effective_model = _resolve_allowed_model(req.model, session)

    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=req.api_key.strip() or DEFAULT_API_KEY,
            language=req.language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
            upload_to_drive=req.upload_to_drive,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline = AkkordPipeline(config, oauth_credentials=oauth_creds)
    try:
        sheets = pipeline.scan_folder(req.folder)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.selected_ids:
        allowed = set(req.selected_ids)
        sheets = [s for s in sheets if s.id in allowed or s.name in allowed]

    if not sheets:
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Aucune partition PDF trouvée dans ce dossier. S'il est privé, cliquez d'abord sur « Se connecter avec Google » en haut à droite.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"Aucune partition PDF trouvée dans ce dossier avec le compte {session.email}.",
        )

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    reports: list[dict[str, Any]] = []
    for sheet in sheets:
        if activity_manager.is_cancelled() or not activity_manager.can_process_more_today(
            owner_id=owner_id
        ):
            break
        try:
            report = pipeline.process_single_pdf(sheet)
            rep_dict = pipeline.report_to_dict(report)
            if sheet.local_path and sheet.local_path.is_file():
                orig_copy = UPLOADS_DIR / sheet.local_path.name
                if sheet.local_path.resolve() != orig_copy.resolve():
                    shutil.copy2(sheet.local_path, orig_copy)
                rep_dict["original_url"] = f"/api/originals/{orig_copy.name}"
            if report.output_filename:
                rep_dict["download_url"] = f"/api/outputs/{report.output_filename}"
            activity_manager.record_analysis(
                rep_dict,
                user_email=session.email if session else "",
                source=sheet.source,
                owner_id=owner_id,
            )
            reports.append(_sanitize_report_for_session(rep_dict, session))
        except Exception as exc:
            err_rep = {
                "source_name": sheet.name,
                "source_id": sheet.id,
                "mode": "error",
                "error": str(exc),
            }
            activity_manager.record_analysis(
                err_rep,
                user_email=session.email if session else "",
                source=sheet.source,
                owner_id=owner_id,
            )
            reports.append(err_rep)

    is_admin = bool(session and session.is_admin)
    return {
        "folder": req.folder,
        "language": config.language,
        "model": config.model,
        "processed_count": len(reports),
        "reports": reports,
        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
        "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
    }


@app.post("/api/process-stream")
def process_folder_stream(
    request: Request,
    req: ProcessFolderRequest,
    akkord_session: str | None = Cookie(default=None),
) -> StreamingResponse:
    """Stream NDJSON progress events and per-file reports while analyzing a folder."""
    _forbid_samples_access(req.folder)
    session, owner_id = _resolve_request_context(request, akkord_session)
    if not activity_manager.can_process_more_today(owner_id=owner_id):
        owner_lim = activity_manager.get_owner_daily_limit(owner_id)
        raise HTTPException(
            status_code=429,
            detail=f"Limite quotidienne atteinte ({owner_lim}/{owner_lim} partitions PDF analysées aujourd'hui). Le quota sera réinitialisé demain.",
        )
    activity_manager.reset_cancel()
    oauth_creds = session.to_google_credentials() if session else None
    effective_model = _resolve_allowed_model(req.model, session)

    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=req.api_key.strip() or DEFAULT_API_KEY,
            language=req.language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
            upload_to_drive=req.upload_to_drive,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline = AkkordPipeline(config, oauth_credentials=oauth_creds)
    try:
        sheets = pipeline.scan_folder(req.folder)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if req.selected_ids:
        allowed = set(req.selected_ids)
        sheets = [s for s in sheets if s.id in allowed or s.name in allowed]

    if not sheets:
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="Aucune partition PDF trouvée dans ce dossier. S'il est privé, cliquez d'abord sur « Se connecter avec Google » en haut à droite.",
            )
        raise HTTPException(
            status_code=404,
            detail=f"Aucune partition PDF trouvée dans ce dossier avec le compte {session.email}.",
        )

    def event_generator() -> Iterator[str]:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        total = len(sheets)
        stage_weights = {
            "download": 0.15,
            "layout": 0.35,
            "harmony": 0.70,
            "annotate": 0.90,
            "upload": 0.95,
            "done": 1.0,
        }
        all_reports: list[dict[str, Any]] = []

        for idx, sheet in enumerate(sheets):
            if activity_manager.is_cancelled():
                yield json.dumps(
                    {
                        "type": "cancelled",
                        "message": f"Analyse interrompue ({len(all_reports)} partition(s) traitée(s)).",
                        "processed_count": len(all_reports),
                        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    }
                ) + "\n"
                return

            if not activity_manager.can_process_more_today(owner_id=owner_id):
                owner_lim = activity_manager.get_owner_daily_limit(owner_id)
                yield json.dumps(
                    {
                        "type": "quota_reached",
                        "message": f"Limite quotidienne de {owner_lim} partitions atteinte pour aujourd'hui.",
                        "processed_count": len(all_reports),
                        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    }
                ) + "\n"
                break

            file_num = idx + 1
            yield json.dumps(
                {
                    "type": "file_start",
                    "file_index": file_num,
                    "total_files": total,
                    "filename": sheet.name,
                    "percent": round(((idx) / total) * 100),
                }
            ) + "\n"

            step_events: list[str] = []

            def on_step(stage: str, msg: str, _idx: int = idx, _fn: int = file_num, _name: str = sheet.name) -> None:
                w = stage_weights.get(stage, 0.5)
                pct = round(((_idx + w) / total) * 100)
                step_events.append(
                    json.dumps(
                        {
                            "type": "step",
                            "file_index": _fn,
                            "total_files": total,
                            "filename": _name,
                            "stage": stage,
                            "message": msg,
                            "percent": pct,
                        }
                    )
                    + "\n"
                )

            try:
                # Emit initial download/layout step immediately before running
                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "download",
                        "message": f"Lecture / téléchargement de {sheet.name}…",
                        "percent": round(((idx + 0.15) / total) * 100),
                    }
                ) + "\n"

                download_dir = config.output_dir / "_downloads"
                local_pdf = pipeline.drive.download_pdf(sheet, download_dir)

                if activity_manager.is_cancelled():
                    yield json.dumps(
                        {
                            "type": "cancelled",
                            "message": f"Analyse interrompue ({len(all_reports)} partition(s) traitée(s)).",
                            "processed_count": len(all_reports),
                            "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                        }
                    ) + "\n"
                    return

                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "layout",
                        "message": f"Détection des portées et systèmes ({sheet.name})…",
                        "percent": round(((idx + 0.35) / total) * 100),
                    }
                ) + "\n"

                from akkord.pdf_layout import analyze_pdf_layout
                from akkord.pdf_annotator import annotate_music_sheet_pdf
                from akkord.i18n import t

                layouts = analyze_pdf_layout(local_pdf)

                if activity_manager.is_cancelled():
                    yield json.dumps(
                        {
                            "type": "cancelled",
                            "message": f"Analyse interrompue ({len(all_reports)} partition(s) traitée(s)).",
                            "processed_count": len(all_reports),
                            "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                        }
                    ) + "\n"
                    return

                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "harmony",
                        "message": f"Analyse harmonique & lignes de basse ({sheet.name})…",
                        "percent": round(((idx + 0.70) / total) * 100),
                    }
                ) + "\n"

                try:
                    result = pipeline.engine.analyze_sheet(layouts, pdf_path=local_pdf)
                except TypeError:
                    result = pipeline.engine.analyze_sheet(layouts)

                if not result.is_music_sheet:
                    rep_dict = {
                        "source_name": sheet.name,
                        "source_id": sheet.id,
                        "is_music_sheet": False,
                        "has_existing_chords": False,
                        "mode": "skipped",
                        "language": config.language,
                        "model": config.model,
                        "title": result.title or sheet.name,
                        "detected_key": "",
                        "overall_summary": result.overall_summary
                        or "Non détecté comme partition.",
                        "accuracy_score": 0,
                        "annotations_count": 0,
                        "analysis_detail": result.model_dump(),
                        "token_usage": result.token_usage.model_dump() if result.token_usage else None,
                    }
                else:
                    stem = Path(sheet.name).stem
                    suffix = (
                        t(config.language, "file_suffix_analyzed")
                        if result.has_existing_chords
                        else t(config.language, "file_suffix_added")
                    )
                    output_filename = f"{stem}{suffix}"
                    output_pdf_path = config.output_dir / output_filename

                    yield json.dumps(
                        {
                            "type": "step",
                            "file_index": file_num,
                            "total_files": total,
                            "filename": sheet.name,
                            "stage": "annotate",
                            "message": f"Génération du PDF annoté ({output_filename})…",
                            "percent": round(((idx + 0.90) / total) * 100),
                        }
                    ) + "\n"

                    annotate_music_sheet_pdf(
                        input_pdf_path=local_pdf,
                        output_pdf_path=output_pdf_path,
                        layouts=layouts,
                        result=result,
                        language=config.language,
                    )

                    uploaded_info = None
                    if config.upload_to_drive and sheet.drive_folder_id:
                        uploaded_info = pipeline.drive.upload_pdf(
                            local_pdf_path=output_pdf_path,
                            folder_id=sheet.drive_folder_id,
                            remote_name=output_filename,
                        )

                    orig_copy = UPLOADS_DIR / local_pdf.name
                    if local_pdf.resolve() != orig_copy.resolve():
                        shutil.copy2(local_pdf, orig_copy)

                    rep_dict = {
                        "source_name": sheet.name,
                        "source_id": sheet.id,
                        "is_music_sheet": True,
                        "has_existing_chords": result.has_existing_chords,
                        "mode": "analyze" if result.has_existing_chords else "add_chords",
                        "language": config.language,
                        "model": config.model,
                        "title": result.title or stem,
                        "detected_key": result.detected_key,
                        "overall_summary": result.overall_summary,
                        "accuracy_score": result.accuracy_score,
                        "annotations_count": len(result.annotations),
                        "output_filename": output_filename,
                        "output_pdf_path": str(output_pdf_path.resolve()),
                        "uploaded_drive_file": uploaded_info,
                        "analysis_detail": result.model_dump(),
                        "token_usage": result.token_usage.model_dump() if result.token_usage else None,
                        "original_url": f"/api/originals/{orig_copy.name}",
                        "download_url": f"/api/outputs/{output_filename}",
                    }
            except Exception as exc:
                rep_dict = {
                    "source_name": sheet.name,
                    "source_id": sheet.id,
                    "mode": "error",
                    "error": str(exc),
                }

            activity_manager.record_analysis(
                rep_dict,
                user_email=session.email if session else "",
                source=sheet.source,
                owner_id=owner_id,
            )
            client_rep = _sanitize_report_for_session(rep_dict, session)
            all_reports.append(client_rep)
            is_admin = bool(session and session.is_admin)
            yield json.dumps(
                {
                    "type": "file_done",
                    "file_index": file_num,
                    "total_files": total,
                    "filename": sheet.name,
                    "percent": round((file_num / total) * 100),
                    "report": client_rep,
                    "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
                }
            ) + "\n"

        is_admin = bool(session and session.is_admin)
        yield json.dumps(
            {
                "type": "batch_done",
                "processed_count": len(all_reports),
                "reports": all_reports,
                "percent": 100,
                "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
            }
        ) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-transform",
        },
    )


@app.post("/api/process-upload")
async def process_uploaded_pdfs(
    request: Request,
    files: list[UploadFile] = File(...),
    language: str = Form(DEFAULT_LANGUAGE),
    model: str = Form(DEFAULT_MODEL),
    api_key: str = Form(DEFAULT_API_KEY),
    akkord_session: str | None = Cookie(default=None),
) -> dict[str, Any]:
    """Process one or more directly uploaded PDF music sheets and return annotated PDF URLs."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    if not activity_manager.can_process_more_today(owner_id=owner_id):
        owner_lim = activity_manager.get_owner_daily_limit(owner_id)
        raise HTTPException(
            status_code=429,
            detail=f"Limite quotidienne atteinte ({owner_lim}/{owner_lim} partitions PDF analysées aujourd'hui). Le quota sera réinitialisé demain.",
        )
    activity_manager.reset_cancel()
    effective_model = _resolve_allowed_model(model, session)
    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=api_key.strip() or DEFAULT_API_KEY,
            language=language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pipeline = AkkordPipeline(config)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    for up in files:
        if activity_manager.is_cancelled() or not activity_manager.can_process_more_today(
            owner_id=owner_id
        ):
            break
        fname = Path(up.filename or "sheet.pdf").name
        if not fname.lower().endswith(".pdf"):
            continue
        dest = UPLOADS_DIR / fname
        with open(dest, "wb") as out_f:
            shutil.copyfileobj(up.file, out_f)

        sheet = SheetFile(
            id=fname,
            name=fname,
            source="upload",
            local_path=dest,
        )
        try:
            report = pipeline.process_single_pdf(sheet)
            rep_dict = pipeline.report_to_dict(report)
            rep_dict["original_url"] = f"/api/originals/{fname}"
            if report.output_filename:
                rep_dict["download_url"] = f"/api/outputs/{report.output_filename}"
            activity_manager.record_analysis(
                rep_dict,
                user_email=session.email if session else "",
                source="upload",
                owner_id=owner_id,
            )
            reports.append(_sanitize_report_for_session(rep_dict, session))
        except Exception as exc:
            err_rep = {
                "source_name": fname,
                "source_id": fname,
                "mode": "error",
                "error": str(exc),
            }
            activity_manager.record_analysis(
                err_rep,
                user_email=session.email if session else "",
                source="upload",
                owner_id=owner_id,
            )
            reports.append(err_rep)

    if not reports:
        raise HTTPException(
            status_code=400,
            detail="Please upload at least one valid .pdf music sheet file.",
        )

    is_admin = bool(session and session.is_admin)
    return {
        "language": config.language,
        "model": config.model,
        "processed_count": len(reports),
        "reports": reports,
        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
        "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
    }


@app.post("/api/process-upload-stream")
def process_uploaded_pdfs_stream(
    request: Request,
    files: list[UploadFile] = File(...),
    language: str = Form(DEFAULT_LANGUAGE),
    model: str = Form(DEFAULT_MODEL),
    api_key: str = Form(DEFAULT_API_KEY),
    akkord_session: str | None = Cookie(default=None),
) -> StreamingResponse:
    """Stream real-time NDJSON progress events while processing uploaded PDF music sheets."""
    session, owner_id = _resolve_request_context(request, akkord_session)
    if not activity_manager.can_process_more_today(owner_id=owner_id):
        owner_lim = activity_manager.get_owner_daily_limit(owner_id)
        raise HTTPException(
            status_code=429,
            detail=f"Limite quotidienne atteinte ({owner_lim}/{owner_lim} partitions PDF analysées aujourd'hui). Le quota sera réinitialisé demain.",
        )
    activity_manager.reset_cancel()
    effective_model = _resolve_allowed_model(model, session)
    try:
        config = AkkordConfig(
            model=effective_model,
            api_key=api_key.strip() or DEFAULT_API_KEY,
            language=language.strip() or DEFAULT_LANGUAGE,
            output_dir=OUTPUTS_DIR,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    saved_sheets: list[SheetFile] = []
    for up in files:
        fname = Path(up.filename or "sheet.pdf").name
        if not fname.lower().endswith(".pdf"):
            continue
        dest = UPLOADS_DIR / fname
        with open(dest, "wb") as out_f:
            shutil.copyfileobj(up.file, out_f)
        saved_sheets.append(
            SheetFile(
                id=fname,
                name=fname,
                source="upload",
                local_path=dest,
            )
        )

    if not saved_sheets:
        raise HTTPException(
            status_code=400,
            detail="Veuillez sélectionner au moins un fichier PDF valide.",
        )

    pipeline = AkkordPipeline(config)

    def event_generator() -> Iterator[str]:
        from akkord.i18n import t
        from akkord.pdf_annotator import annotate_music_sheet_pdf
        from akkord.pdf_layout import analyze_pdf_layout

        total = len(saved_sheets)
        all_reports: list[dict[str, Any]] = []

        for idx, sheet in enumerate(saved_sheets):
            if activity_manager.is_cancelled():
                yield json.dumps(
                    {
                        "type": "cancelled",
                        "message": f"Analyse interrompue ({len(all_reports)} partition(s) traitée(s)).",
                        "processed_count": len(all_reports),
                        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    }
                ) + "\n"
                return

            if not activity_manager.can_process_more_today(owner_id=owner_id):
                owner_lim = activity_manager.get_owner_daily_limit(owner_id)
                yield json.dumps(
                    {
                        "type": "quota_reached",
                        "message": f"Limite quotidienne de {owner_lim} partitions atteinte pour aujourd'hui.",
                        "processed_count": len(all_reports),
                        "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    }
                ) + "\n"
                break

            file_num = idx + 1
            local_pdf = sheet.local_path
            assert local_pdf is not None

            yield json.dumps(
                {
                    "type": "file_start",
                    "file_index": file_num,
                    "total_files": total,
                    "filename": sheet.name,
                    "percent": round((idx / total) * 100),
                }
            ) + "\n"

            try:
                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "download",
                        "message": f"Lecture du fichier PDF ({sheet.name})…",
                        "percent": round(((idx + 0.15) / total) * 100),
                    }
                ) + "\n"

                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "layout",
                        "message": f"Détection des portées et systèmes ({sheet.name})…",
                        "percent": round(((idx + 0.35) / total) * 100),
                    }
                ) + "\n"

                layouts = analyze_pdf_layout(local_pdf)

                if activity_manager.is_cancelled():
                    yield json.dumps(
                        {
                            "type": "cancelled",
                            "message": f"Analyse interrompue ({len(all_reports)} partition(s) traitée(s)).",
                            "processed_count": len(all_reports),
                            "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                        }
                    ) + "\n"
                    return

                yield json.dumps(
                    {
                        "type": "step",
                        "file_index": file_num,
                        "total_files": total,
                        "filename": sheet.name,
                        "stage": "harmony",
                        "message": f"Analyse harmonique & lignes de basse ({sheet.name})…",
                        "percent": round(((idx + 0.70) / total) * 100),
                    }
                ) + "\n"

                try:
                    result = pipeline.engine.analyze_sheet(layouts, pdf_path=local_pdf)
                except TypeError:
                    result = pipeline.engine.analyze_sheet(layouts)

                if not result.is_music_sheet:
                    rep_dict = {
                        "source_name": sheet.name,
                        "source_id": sheet.id,
                        "is_music_sheet": False,
                        "has_existing_chords": False,
                        "mode": "skipped",
                        "language": config.language,
                        "model": config.model,
                        "title": result.title or sheet.name,
                        "detected_key": "",
                        "overall_summary": result.overall_summary
                        or "Non détecté comme partition.",
                        "accuracy_score": 0,
                        "annotations_count": 0,
                        "analysis_detail": result.model_dump(),
                        "token_usage": result.token_usage.model_dump() if result.token_usage else None,
                    }
                else:
                    stem = Path(sheet.name).stem
                    suffix = (
                        t(config.language, "file_suffix_analyzed")
                        if result.has_existing_chords
                        else t(config.language, "file_suffix_added")
                    )
                    output_filename = f"{stem}{suffix}"
                    output_pdf_path = config.output_dir / output_filename

                    yield json.dumps(
                        {
                            "type": "step",
                            "file_index": file_num,
                            "total_files": total,
                            "filename": sheet.name,
                            "stage": "annotate",
                            "message": f"Génération du PDF annoté ({output_filename})…",
                            "percent": round(((idx + 0.90) / total) * 100),
                        }
                    ) + "\n"

                    annotate_music_sheet_pdf(
                        input_pdf_path=local_pdf,
                        output_pdf_path=output_pdf_path,
                        layouts=layouts,
                        result=result,
                        language=config.language,
                    )

                    rep_dict = {
                        "source_name": sheet.name,
                        "source_id": sheet.id,
                        "is_music_sheet": True,
                        "has_existing_chords": result.has_existing_chords,
                        "mode": "analyze" if result.has_existing_chords else "add_chords",
                        "language": config.language,
                        "model": config.model,
                        "title": result.title or stem,
                        "detected_key": result.detected_key,
                        "overall_summary": result.overall_summary,
                        "accuracy_score": result.accuracy_score,
                        "annotations_count": len(result.annotations),
                        "output_filename": output_filename,
                        "output_pdf_path": str(output_pdf_path.resolve()),
                        "uploaded_drive_file": None,
                        "analysis_detail": result.model_dump(),
                        "token_usage": result.token_usage.model_dump() if result.token_usage else None,
                        "original_url": f"/api/originals/{sheet.name}",
                        "download_url": f"/api/outputs/{output_filename}",
                    }
            except Exception as exc:
                rep_dict = {
                    "source_name": sheet.name,
                    "source_id": sheet.id,
                    "mode": "error",
                    "error": str(exc),
                }

            activity_manager.record_analysis(
                rep_dict,
                user_email=session.email if session else "",
                source="upload",
                owner_id=owner_id,
            )
            client_rep = _sanitize_report_for_session(rep_dict, session)
            all_reports.append(client_rep)
            is_admin = bool(session and session.is_admin)
            yield json.dumps(
                {
                    "type": "file_done",
                    "file_index": file_num,
                    "total_files": total,
                    "filename": sheet.name,
                    "percent": round((file_num / total) * 100),
                    "report": client_rep,
                    "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                    "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
                }
            ) + "\n"

        is_admin = bool(session and session.is_admin)
        yield json.dumps(
            {
                "type": "batch_done",
                "processed_count": len(all_reports),
                "reports": all_reports,
                "percent": 100,
                "daily_quota": activity_manager.get_quota_status(owner_id=owner_id),
                "admin_usage": activity_manager.get_usage_summary() if is_admin else None,
            }
        ) + "\n"

    return StreamingResponse(
        event_generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache, no-transform",
        },
    )


def _build_content_disposition(disposition_type: str, filename: str) -> str:
    """Build an ASCII-safe RFC 5987 Content-Disposition header for Unicode/Cyrillic filenames."""
    from urllib.parse import quote

    try:
        filename.encode("latin-1")
        escaped = filename.replace("\\", "\\\\").replace('"', '\\"')
        return f'{disposition_type}; filename="{escaped}"'
    except UnicodeEncodeError:
        utf8_filename = quote(filename)
        return f"{disposition_type}; filename*=utf-8''{utf8_filename}"


@app.get("/api/jobs/{job_id}/originals/{filename}", response_model=None)
def get_job_original_pdf(
    job_id: str,
    filename: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> Response:
    """Serve the original PDF for a specific batch job (strictly owner-checked)."""
    _, owner_id = _resolve_request_context(request, akkord_session)
    job = job_queue_manager.get_job(job_id, reload_from_gcs=gcs_backend.enabled)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    if not job_queue_manager.job_belongs_to_owner(job, owner_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce document est privé et appartient à un autre utilisateur.",
        )
    safe_name = Path(filename).name
    raw = job_queue_manager.read_original_pdf(safe_name, job_id=job_id)
    if raw:
        return Response(
            content=raw,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _build_content_disposition("inline", safe_name)
            },
        )
    target = (UPLOADS_DIR / safe_name).resolve()
    if target.is_file():
        return FileResponse(
            path=str(target),
            media_type="application/pdf",
            filename=safe_name,
            content_disposition_type="inline",
        )
    raise HTTPException(
        status_code=404, detail=f"Original file '{safe_name}' not found."
    )


@app.get("/api/jobs/{job_id}/outputs/{filename}", response_model=None)
def get_job_output_pdf(
    job_id: str,
    filename: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> Response:
    """Serve the annotated output PDF for a specific batch job (strictly owner-checked)."""
    _, owner_id = _resolve_request_context(request, akkord_session)
    job = job_queue_manager.get_job(job_id, reload_from_gcs=gcs_backend.enabled)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' introuvable.")
    if not job_queue_manager.job_belongs_to_owner(job, owner_id):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce document est privé et appartient à un autre utilisateur.",
        )
    safe_name = Path(filename).name
    raw = job_queue_manager.read_output_pdf(safe_name, job_id=job_id)
    if raw:
        return Response(
            content=raw,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _build_content_disposition("inline", safe_name)
            },
        )
    target = (OUTPUTS_DIR / safe_name).resolve()
    if target.is_file():
        return FileResponse(
            path=str(target),
            media_type="application/pdf",
            filename=safe_name,
            content_disposition_type="inline",
        )
    raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")


@app.get("/api/originals/{filename}", response_model=None)
def get_original_pdf(
    filename: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> Response:
    _, owner_id = _resolve_request_context(request, akkord_session)
    safe_name = Path(filename).name
    if not job_queue_manager.user_owns_filename(
        owner_id, safe_name, is_original=True
    ):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce document est privé et appartient à un autre utilisateur.",
        )
    target = (UPLOADS_DIR / safe_name).resolve()
    if target.is_file():
        return FileResponse(
            path=str(target),
            media_type="application/pdf",
            filename=safe_name,
            content_disposition_type="inline",
        )
    raw = job_queue_manager.read_original_pdf(safe_name)
    if raw:
        return Response(
            content=raw,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _build_content_disposition("inline", safe_name)
            },
        )
    raise HTTPException(
        status_code=404, detail=f"Original file '{safe_name}' not found."
    )


@app.get("/api/outputs/{filename}", response_model=None)
def get_output_pdf(
    filename: str,
    request: Request,
    akkord_session: str | None = Cookie(default=None),
) -> Response:
    _, owner_id = _resolve_request_context(request, akkord_session)
    safe_name = Path(filename).name
    if not job_queue_manager.user_owns_filename(
        owner_id, safe_name, is_original=False
    ):
        raise HTTPException(
            status_code=403,
            detail="Accès refusé : ce document est privé et appartient à un autre utilisateur.",
        )
    target = (OUTPUTS_DIR / safe_name).resolve()
    if target.is_file():
        return FileResponse(
            path=str(target),
            media_type="application/pdf",
            filename=safe_name,
            content_disposition_type="inline",
        )
    raw = job_queue_manager.read_output_pdf(safe_name)
    if raw:
        return Response(
            content=raw,
            media_type="application/pdf",
            headers={
                "Content-Disposition": _build_content_disposition("inline", safe_name)
            },
        )
    raise HTTPException(status_code=404, detail=f"File '{safe_name}' not found.")
