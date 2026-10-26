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
"""Event-driven job queue, Cloud Tasks dispatcher, and GCS persistent storage backend for Akkord."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
import gc
import io
import json
import os
from pathlib import Path
import queue
import secrets
import shutil
import tempfile
import threading
import time
from typing import Any
from urllib.parse import quote
import zipfile
from zoneinfo import ZoneInfo

import httpx

from akkord.activity import DAILY_FILE_LIMIT, ActivityManager
from akkord.config import AkkordConfig
from akkord.drive import DriveConnector, SheetFile
from akkord.harmony import HarmonyAnalysisResult, compute_harmony_accuracy_score
from akkord.oauth import (
    ADMIN_EMAIL,
    DEFAULT_OAUTH_CLIENT_ID,
    DEFAULT_OAUTH_CLIENT_SECRET,
    normalize_record_owner_id,
)
from akkord.pipeline import AkkordPipeline

PARIS_TZ = ZoneInfo("Europe/Paris")
DEFAULT_GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "alexismp-runner")
DEFAULT_GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "europe-west1")
DEFAULT_GCS_BUCKET = os.environ.get("AKKORD_GCS_BUCKET", "alexismp-runner-akkord-data")
DEFAULT_TASKS_QUEUE = os.environ.get("AKKORD_TASKS_QUEUE", "akkord-pdf-queue")
DEFAULT_SERVICE_URL = os.environ.get(
    "AKKORD_SERVICE_URL", "https://akkord-2500276981.europe-west1.run.app"
)


class GCSStorageBackend:
    """Hybrid storage backend using Google Cloud Storage REST API on Cloud Run + local disk fallback."""

    def __init__(self, local_dir: Path, bucket_name: str = DEFAULT_GCS_BUCKET) -> None:
        self.local_dir = local_dir
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.bucket_name = bucket_name
        # Enable remote GCS automatically when running on Cloud Run (K_SERVICE) or explicitly via AKKORD_ENABLE_GCS=1
        self.enabled = bool(
            os.environ.get("K_SERVICE")
            or os.environ.get("AKKORD_ENABLE_GCS", "").strip() in ("1", "true", "yes")
        )
        self._creds: Any = None
        self._lock = threading.Lock()

    def _get_token(self) -> str | None:
        if not self.enabled:
            return None
        try:
            import google.auth
            from google.auth.transport.requests import Request

            with self._lock:
                if self._creds is None:
                    self._creds, _ = google.auth.default(
                        scopes=["https://www.googleapis.com/auth/cloud-platform"]
                    )
                if not self._creds.valid or getattr(self._creds, "expired", False):
                    self._creds.refresh(Request())
                return getattr(self._creds, "token", None)
        except Exception:
            return None

    def _local_path(self, key: str) -> Path:
        target = (self.local_dir / "_gcs_mirror" / key).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def write_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        keep_local_copy: bool = True,
    ) -> bool:
        """Persist bytes to GCS (if enabled) and optionally keep a local mirror."""
        if keep_local_copy or not self.enabled:
            lp = self._local_path(key)
            lp.write_bytes(data)

        token = self._get_token()
        if not token:
            return True

        url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket_name}/o"
        params = {"uploadType": "media", "name": key}
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
            "User-Agent": "gcs-skills/1.0 (skill:google-cloud-storage-bucket-architect)",
        }
        try:
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(url, params=params, headers=headers, content=data)
                return resp.status_code in (200, 201)
        except Exception:
            return False

    def read_bytes(self, key: str) -> bytes | None:
        """Read bytes from GCS (or local mirror)."""
        token = self._get_token()
        if token:
            encoded = quote(key, safe="")
            url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket_name}/o/{encoded}"
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "gcs-skills/1.0 (skill:google-cloud-storage-bucket-architect)",
            }
            try:
                with httpx.Client(timeout=45.0) as client:
                    resp = client.get(url, params={"alt": "media"}, headers=headers)
                    if resp.status_code == 200:
                        return resp.content
            except Exception:
                pass

        lp = self._local_path(key)
        if lp.is_file():
            return lp.read_bytes()
        return None

    def write_json(self, key: str, payload: Any) -> bool:
        raw = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return self.write_bytes(
            key, raw, content_type="application/json; charset=utf-8", keep_local_copy=True
        )

    def read_json(self, key: str) -> Any | None:
        raw = self.read_bytes(key)
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return None

    def list_keys(self, prefix: str) -> list[str]:
        keys: set[str] = set()
        mirror_root = (self.local_dir / "_gcs_mirror").resolve()
        prefix_dir = (mirror_root / prefix).resolve()
        if prefix_dir.exists():
            if prefix_dir.is_dir():
                for p in prefix_dir.rglob("*"):
                    if p.is_file():
                        keys.add(str(p.relative_to(mirror_root)).replace("\\", "/"))
        elif mirror_root.exists():
            for p in mirror_root.rglob("*"):
                if p.is_file():
                    rel = str(p.relative_to(mirror_root)).replace("\\", "/")
                    if rel.startswith(prefix):
                        keys.add(rel)

        token = self._get_token()
        if token:
            url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket_name}/o"
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "gcs-skills/1.0 (skill:google-cloud-storage-bucket-architect)",
            }
            try:
                with httpx.Client(timeout=20.0) as client:
                    resp = client.get(url, params={"prefix": prefix}, headers=headers)
                    if resp.status_code == 200:
                        for item in resp.json().get("items", []):
                            name = item.get("name")
                            if name:
                                keys.add(name)
            except Exception:
                pass
        return sorted(keys)


@dataclass
class JobItem:
    """Single PDF music sheet item inside an asynchronous batch job."""

    item_id: str
    index: int  # 1-based position in the batch
    filename: str
    source: str  # "drive" | "upload" | "local"
    drive_file_id: str = ""
    drive_folder_id: str = ""
    local_path: str = ""
    gcs_original_key: str = ""
    status: str = "queued"  # "queued" | "deferred_next_day" | "processing" | "completed" | "skipped" | "error" | "cancelled"
    scheduled_for: str = ""  # ISO date/time when deferred to next day(s)
    stage: str = ""  # "download" | "layout" | "harmony" | "annotate" | "upload" | "done"
    stage_message: str = ""
    percent: int = 0
    output_filename: str = ""
    download_url: str = ""
    original_url: str = ""
    error: str = ""
    report: dict[str, Any] | None = None


@dataclass
class BatchJob:
    """Asynchronous batch job tracking tens or hundreds of PDF music sheets."""

    job_id: str
    created_at: str
    updated_at: str
    folder: str
    language: str
    model: str
    upload_to_drive: bool
    user_email: str
    is_admin: bool
    status: str = "running"  # "running" | "partially_deferred" | "completed" | "cancelled"
    message: str = ""
    total_files: int = 0
    completed_files: int = 0
    queued_today_files: int = 0
    deferred_files: int = 0
    error_files: int = 0
    cancelled_files: int = 0
    active_item_index: int = 0
    active_filename: str = ""
    active_stage: str = ""
    active_stage_message: str = ""
    percent: int = 0
    items: list[JobItem] = field(default_factory=list)
    oauth_tokens: dict[str, str] = field(default_factory=dict)
    owner_id: str = ""


class JobQueueManager:
    """Coordinates non-blocking batch jobs, 25/day multi-day scheduling, Cloud Tasks, and memory-safe workers."""

    def __init__(
        self,
        storage_dir: Path,
        activity_manager: ActivityManager,
        gcs_backend: GCSStorageBackend | None = None,
    ) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.activity_manager = activity_manager
        self.gcs = gcs_backend or GCSStorageBackend(storage_dir)
        self._lock = threading.RLock()
        self._jobs: dict[str, BatchJob] = {}
        self._last_jobs_sync_ts: float = 0.0
        self._local_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self._worker_started = False
        self.cloud_tasks_enabled = bool(
            os.environ.get("K_SERVICE")
            or os.environ.get("AKKORD_ENABLE_CLOUD_TASKS", "").strip() in ("1", "true", "yes")
        )
        self._load_existing_jobs()

    def _now_paris(self) -> datetime:
        return datetime.now(PARIS_TZ)

    @staticmethod
    def _construct_batch_job_from_dict(data: dict[str, Any]) -> BatchJob:
        allowed_item_keys = set(JobItem.__dataclass_fields__.keys())
        allowed_job_keys = set(BatchJob.__dataclass_fields__.keys()) - {"items"}
        items = [
            JobItem(**{k: v for k, v in it.items() if k in allowed_item_keys})
            for it in (data.get("items") or [])
            if isinstance(it, dict)
        ]
        job_kwargs = {k: v for k, v in data.items() if k in allowed_job_keys}
        job = BatchJob(**job_kwargs, items=items)
        job.owner_id = normalize_record_owner_id(job.owner_id, job.user_email)
        return job

    @staticmethod
    def job_belongs_to_owner(job: BatchJob, owner_id: str) -> bool:
        """Return True iff the given BatchJob belongs to `owner_id`."""
        if not owner_id:
            return False
        return normalize_record_owner_id(job.owner_id, job.user_email) == owner_id

    def _load_existing_jobs(self) -> None:
        fs = getattr(self.activity_manager, "firestore_backend", None)
        fs_enabled = fs is not None and getattr(fs, "enabled", False)
        for key in self.gcs.list_keys("jobs/"):
            if not key.endswith(".json"):
                continue
            jid_hint = Path(key).stem
            existing_job = self._jobs.get(jid_hint)
            if existing_job is not None and existing_job.status in ("completed", "cancelled"):
                continue
            data = self.gcs.read_json(key)
            if not isinstance(data, dict) or "job_id" not in data:
                continue
            try:
                job = self._construct_batch_job_from_dict(data)
                self._jobs[job.job_id] = job
            except Exception:
                pass

        if fs_enabled:
            try:
                fs_jobs = fs.list_documents("akkord_jobs")
                for jid, data in fs_jobs.items():
                    if jid in self._jobs or not isinstance(data, dict) or "job_id" not in data:
                        continue
                    self._jobs[jid] = self._construct_batch_job_from_dict(data)
            except Exception:
                pass
        self._last_jobs_sync_ts = time.monotonic()

    def _recompute_job_Rollup(self, job: BatchJob) -> None:
        total = len(job.items)
        completed = sum(1 for it in job.items if it.status in ("completed", "skipped"))
        errors = sum(1 for it in job.items if it.status == "error")
        cancelled = sum(1 for it in job.items if it.status == "cancelled")
        deferred = sum(1 for it in job.items if it.status == "deferred_next_day")
        queued_today = sum(1 for it in job.items if it.status in ("queued", "processing"))

        job.total_files = total
        job.completed_files = completed
        job.error_files = errors
        job.cancelled_files = cancelled
        job.deferred_files = deferred
        job.queued_today_files = queued_today
        job.updated_at = self._now_paris().isoformat(timespec="seconds")

        active_it = next((it for it in job.items if it.status == "processing"), None)
        if active_it is not None:
            job.active_item_index = active_it.index
            job.active_filename = active_it.filename
            job.active_stage = active_it.stage or "download"
            job.active_stage_message = (
                active_it.stage_message or f"Traitement de {active_it.filename}…"
            )
        else:
            next_queued = next((it for it in job.items if it.status == "queued"), None)
            if next_queued is not None:
                job.active_item_index = next_queued.index
                job.active_filename = next_queued.filename
                job.active_stage = "download"
                job.active_stage_message = f"En file d'attente : {next_queued.filename}…"
            else:
                job.active_stage = "done"

        finished_count = completed + errors + cancelled
        if total > 0:
            active_fraction = (active_it.percent / 100.0) if active_it else 0.0
            job.percent = min(
                100, round(((finished_count + active_fraction) / total) * 100)
            )
        else:
            job.percent = 100

        if cancelled > 0 and queued_today == 0 and deferred == 0:
            job.status = "cancelled"
            job.message = (
                f"⏹ Analyse interrompue ({completed} partition(s) terminée(s), "
                f"{cancelled} annulée(s))."
            )
        elif queued_today == 0 and deferred > 0:
            job.status = "partially_deferred"
            next_dates = sorted({it.scheduled_for[:10] for it in job.items if it.scheduled_for})
            next_date_label = next_dates[0] if next_dates else "demain"
            job.message = (
                f"✅ Lot du jour terminé ({completed} partition(s) traitée(s)). "
                f"📅 {deferred} partition(s) supplémentaire(s) planifiée(s) automatiquement à partir du {next_date_label} (limite de {DAILY_FILE_LIMIT}/jour)."
            )
        elif queued_today == 0 and deferred == 0:
            job.status = "completed"
            job.percent = 100
            job.message = (
                f"✅ Traitement terminé : {completed} partition(s) annotée(s)"
                + (f" ({errors} erreur(s))" if errors else "")
                + "."
            )
        else:
            job.status = "running"
            if deferred > 0:
                job.message = (
                    f"Traitement en cours ({completed}/{total - deferred} aujourd'hui) • "
                    f"📅 {deferred} partition(s) planifiée(s) pour demain (quota {DAILY_FILE_LIMIT}/j)."
                )
            else:
                job.message = (
                    job.active_stage_message
                    or f"Traitement en cours ({completed}/{total})…"
                )

    def _save_job(self, job: BatchJob, preserve_item_id: str | None = None) -> None:
        with self._lock:
            if self.gcs.enabled:
                try:
                    remote = self.gcs.read_json(f"jobs/{job.job_id}.json")
                    if isinstance(remote, dict) and isinstance(remote.get("items"), list):
                        remote_by_id = {
                            str(rit.get("item_id")): rit
                            for rit in remote["items"]
                            if isinstance(rit, dict) and rit.get("item_id")
                        }
                        terminal = {"completed", "skipped", "error", "cancelled"}
                        for idx_it, local_it in enumerate(job.items):
                            if local_it.item_id == preserve_item_id:
                                continue
                            rem_it = remote_by_id.get(local_it.item_id)
                            if (
                                rem_it is not None
                                and rem_it.get("status") in terminal
                                and local_it.status not in terminal
                            ):
                                job.items[idx_it] = JobItem(**rem_it)
                except Exception:
                    pass
            self._recompute_job_Rollup(job)
            self._jobs[job.job_id] = job
            payload = asdict(job)
            self.gcs.write_json(f"jobs/{job.job_id}.json", payload)
            fs = getattr(self.activity_manager, "firestore_backend", None)
            if fs is not None:
                try:
                    fs.set_document("akkord_jobs", job.job_id, payload)
                except Exception:
                    pass

    def get_job(self, job_id: str, reload_from_gcs: bool = False) -> BatchJob | None:
        with self._lock:
            if reload_from_gcs or job_id not in self._jobs:
                data = self.gcs.read_json(f"jobs/{job_id}.json")
                if not isinstance(data, dict) or "job_id" not in data:
                    fs = getattr(self.activity_manager, "firestore_backend", None)
                    if fs is not None:
                        data = fs.get_document("akkord_jobs", job_id)
                if isinstance(data, dict) and "job_id" in data:
                    self._jobs[job_id] = self._construct_batch_job_from_dict(data)
            return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 10, owner_id: str | None = None) -> list[BatchJob]:
        with self._lock:
            now_ts = time.monotonic()
            if (self.gcs.enabled or getattr(getattr(self.activity_manager, "firestore_backend", None), "enabled", False)) and (
                not self._jobs or (now_ts - self._last_jobs_sync_ts) > 5.0
            ):
                self._load_existing_jobs()
            all_jobs = list(self._jobs.values())
            if owner_id is not None:
                all_jobs = [j for j in all_jobs if self.job_belongs_to_owner(j, owner_id)]
            jobs = sorted(all_jobs, key=lambda j: j.created_at, reverse=True)
            return jobs[:limit]

    def get_recent_history(
        self, limit: int = 25, is_admin: bool = False, owner_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Collect recent analyzed items across batch jobs and daily activity logs for `owner_id` so page refresh restores only the caller's history."""
        recent_jobs = self.list_jobs(limit=15, owner_id=owner_id)
        history_items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for job in recent_jobs:
            serialized = self.serialize_job_for_client(job, is_admin=is_admin)
            for it in serialized.get("items", []):
                fname = str(it.get("filename") or "")
                out_fname = str(it.get("output_filename") or "")
                dedup_key = f"{fname}::{out_fname}" if out_fname else f"{job.job_id}::{it.get('item_id')}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                it_copy = dict(it)
                it_copy["job_id"] = job.job_id
                it_copy["item_id"] = f"{job.job_id}-{it.get('item_id', '')}"
                history_items.append(it_copy)
                if len(history_items) >= limit:
                    return history_items

        # Also include any standalone analyses recorded in ActivityManager that belong to `owner_id`
        try:
            today_rec = self.activity_manager.get_today_record()
            for idx, entry in enumerate(reversed(today_rec.entries), start=1):
                entry_owner = normalize_record_owner_id(
                    getattr(entry, "owner_id", ""), entry.user_email
                )
                if owner_id is not None and entry_owner != owner_id:
                    continue
                dedup_key = f"{entry.filename}::{entry.output_filename}"
                if dedup_key in seen_keys or any(
                    k.startswith(f"{entry.filename}::") for k in seen_keys
                ):
                    continue
                seen_keys.add(dedup_key)
                safe_orig = Path(entry.filename).name if entry.filename else ""
                safe_out = Path(entry.output_filename).name if entry.output_filename else ""
                rep_dict: dict[str, Any] = {
                    "source_name": entry.filename,
                    "title": entry.title or entry.filename,
                    "detected_key": entry.detected_key or "N/A",
                    "mode": entry.mode,
                    "accuracy_score": entry.accuracy_score,
                    "annotations_count": entry.annotations_count,
                    "language": entry.language or "fr",
                    "model": entry.model,
                    "output_filename": safe_out,
                    "download_url": f"/api/outputs/{quote(safe_out)}" if safe_out else "",
                    "original_url": f"/api/originals/{quote(safe_orig)}" if safe_orig else "",
                    "overall_summary": entry.overall_summary,
                    "error": entry.error,
                }
                if is_admin and entry.total_tokens > 0:
                    rep_dict["token_usage"] = {
                        "model": entry.model,
                        "input_tokens": entry.input_tokens,
                        "output_tokens": entry.output_tokens,
                        "thinking_tokens": entry.thinking_tokens,
                        "cached_tokens": entry.cached_tokens,
                        "total_tokens": entry.total_tokens,
                        "estimated_cost_usd": entry.estimated_cost_usd,
                        "estimated_cost_eur": entry.estimated_cost_eur,
                        "source": entry.token_source,
                    }
                history_items.append(
                    {
                        "item_id": f"activity-{today_rec.date}-{idx:03d}",
                        "index": len(history_items) + 1,
                        "filename": entry.filename,
                        "source": entry.source,
                        "status": "error" if entry.mode == "error" else "completed",
                        "stage": "done",
                        "stage_message": f"Terminé ({entry.timestamp})",
                        "percent": 100,
                        "output_filename": safe_out,
                        "download_url": rep_dict["download_url"],
                        "original_url": rep_dict["original_url"],
                        "error": entry.error,
                        "report": rep_dict,
                    }
                )
                if len(history_items) >= limit:
                    break
        except Exception:
            pass

        return history_items

    def serialize_job_for_client(
        self, job: BatchJob, is_admin: bool = False
    ) -> dict[str, Any]:
        """Return a lightweight JSON-serializable view of the job (without OAuth secrets or PNG buffers)."""
        with self._lock:
            self._recompute_job_Rollup(job)
            data = asdict(job)
        data.pop("oauth_tokens", None)
        for it in data.get("items", []):
            safe_orig = Path(str(it.get("filename") or "")).name
            safe_out = Path(str(it.get("output_filename") or "")).name
            if safe_orig:
                it["original_url"] = f"/api/jobs/{job.job_id}/originals/{quote(safe_orig)}"
            if safe_out:
                it["download_url"] = f"/api/jobs/{job.job_id}/outputs/{quote(safe_out)}"
            rep = it.get("report")
            if isinstance(rep, dict):
                if safe_orig:
                    rep["original_url"] = it["original_url"]
                if safe_out:
                    rep["download_url"] = it["download_url"]
                detail = rep.get("analysis_detail")
                if isinstance(detail, dict) and rep.get("mode") == "analyze":
                    try:
                        res_obj = HarmonyAnalysisResult.model_validate(detail)
                        recomputed = compute_harmony_accuracy_score(res_obj)
                        rep["accuracy_score"] = recomputed
                        detail["accuracy_score"] = recomputed
                    except Exception:
                        pass
                if not is_admin:
                    rep.pop("token_usage", None)
                    if isinstance(detail, dict):
                        detail.pop("token_usage", None)
        data["daily_quota"] = self.activity_manager.get_quota_status()
        data["admin_usage"] = (
            self.activity_manager.get_usage_summary() if is_admin else None
        )
        return data

    def _compute_schedule_for_excess_item(self, excess_index_zero_based: int) -> datetime:
        """Compute the Paris timestamp (00:05 on Day + K) for items exceeding today's 25-file quota."""
        days_ahead = (excess_index_zero_based // DAILY_FILE_LIMIT) + 1
        now = self._now_paris()
        target_date = (now + timedelta(days=days_ahead)).date()
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            0,
            5,
            0,
            tzinfo=PARIS_TZ,
        )

    def create_batch_job(
        self,
        sheets: list[SheetFile],
        folder: str,
        language: str,
        model: str,
        upload_to_drive: bool,
        user_email: str = "",
        is_admin: bool = False,
        oauth_tokens: dict[str, str] | None = None,
        run_async: bool = True,
        owner_id: str = "",
    ) -> BatchJob:
        """Create a new BatchJob, split items into today's quota vs deferred_next_day, and enqueue tasks."""
        self.activity_manager.reset_cancel()
        now = self._now_paris()
        job_id = f"job-{now.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
        effective_owner_id = normalize_record_owner_id(owner_id, user_email)

        quota = self.activity_manager.get_quota_status()
        remaining_today = int(quota.get("remaining", DAILY_FILE_LIMIT))

        # Also count items already queued/processing today in other active jobs
        with self._lock:
            already_queued_in_active_jobs = sum(
                it.status in ("queued", "processing")
                for j in self._jobs.values()
                if j.status == "running"
                for it in j.items
            )
        available_slots_today = max(0, remaining_today - already_queued_in_active_jobs)

        items: list[JobItem] = []
        for idx, sh in enumerate(sheets, start=1):
            item_id = f"item-{idx:04d}"
            safe_name = Path(sh.name).name
            gcs_orig_key = ""
            if sh.local_path and sh.local_path.is_file():
                gcs_orig_key = f"jobs/{job_id}/originals/{safe_name}"
                try:
                    self.gcs.write_bytes(
                        gcs_orig_key,
                        sh.local_path.read_bytes(),
                        content_type="application/pdf",
                        keep_local_copy=True,
                    )
                except Exception:
                    pass

            if idx <= available_slots_today:
                status = "queued"
                scheduled_for = now.strftime("%Y-%m-%d")
            else:
                status = "deferred_next_day"
                excess_offset = (idx - 1) - available_slots_today
                sched_dt = self._compute_schedule_for_excess_item(excess_offset)
                scheduled_for = sched_dt.isoformat(timespec="minutes")

            items.append(
                JobItem(
                    item_id=item_id,
                    index=idx,
                    filename=sh.name,
                    source=sh.source,
                    drive_file_id=sh.id if sh.source == "drive" else "",
                    drive_folder_id=sh.drive_folder_id or "",
                    local_path=str(sh.local_path) if sh.local_path else "",
                    gcs_original_key=gcs_orig_key,
                    status=status,
                    scheduled_for=scheduled_for,
                    stage="download" if status == "queued" else "deferred",
                    stage_message=(
                        "En file d'attente pour analyse aujourd'hui…"
                        if status == "queued"
                        else f"Reporté automatiquement au {scheduled_for[:10]} (quota de {DAILY_FILE_LIMIT} fichiers/jour)"
                    ),
                    original_url=f"/api/jobs/{job_id}/originals/{quote(safe_name)}",
                )
            )

        job = BatchJob(
            job_id=job_id,
            created_at=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"),
            folder=folder,
            language=language,
            model=model,
            upload_to_drive=upload_to_drive,
            user_email=user_email,
            is_admin=is_admin,
            items=items,
            oauth_tokens=oauth_tokens or {},
            owner_id=effective_owner_id,
        )
        self._save_job(job)

        if run_async:
            self._dispatch_job_items(job)
        return job

    def _dispatch_job_items(self, job: BatchJob) -> None:
        """Dispatch queued items immediately and schedule deferred items via Cloud Tasks (or local worker)."""
        dispatched_to_cloud_tasks = False
        if self.cloud_tasks_enabled:
            dispatched_to_cloud_tasks = self._enqueue_cloud_tasks_for_job(job)

        if not dispatched_to_cloud_tasks:
            self._start_local_worker_if_needed()
            for it in job.items:
                if it.status == "queued":
                    self._local_queue.put((job.job_id, it.item_id))

    def _enqueue_cloud_tasks_for_job(self, job: BatchJob) -> bool:
        """Enqueue one Cloud Task per JobItem (with scheduleTime for deferred items)."""
        token = self.gcs._get_token()
        if not token:
            return False

        queue_path = (
            f"projects/{DEFAULT_GCP_PROJECT}/locations/{DEFAULT_GCP_LOCATION}/"
            f"queues/{DEFAULT_TASKS_QUEUE}"
        )
        api_url = f"https://cloudtasks.googleapis.com/v2/{queue_path}/tasks"
        target_url = f"{DEFAULT_SERVICE_URL.rstrip('/')}/api/internal/tasks/process-file"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        enqueued_any = False
        try:
            with httpx.Client(timeout=20.0) as client:
                for it in job.items:
                    if it.status not in ("queued", "deferred_next_day"):
                        continue
                    body_bytes = json.dumps(
                        {"job_id": job.job_id, "item_id": it.item_id}
                    ).encode("utf-8")
                    task_obj: dict[str, Any] = {
                        "httpRequest": {
                            "httpMethod": "POST",
                            "url": target_url,
                            "headers": {"Content-Type": "application/json"},
                            "body": base64.b64encode(body_bytes).decode("ascii"),
                        }
                    }
                    if it.status == "deferred_next_day" and it.scheduled_for:
                        try:
                            dt = datetime.fromisoformat(it.scheduled_for)
                            utc_iso = dt.astimezone(ZoneInfo("UTC")).strftime(
                                "%Y-%m-%dT%H:%M:%SZ"
                            )
                            task_obj["scheduleTime"] = utc_iso
                        except Exception:
                            pass

                    resp = client.post(
                        api_url, headers=headers, json={"task": task_obj}
                    )
                    if resp.status_code in (200, 201):
                        enqueued_any = True
                    else:
                        return False
        except Exception:
            return False
        return enqueued_any

    def _start_local_worker_if_needed(self) -> None:
        with self._lock:
            if self._worker_started:
                return
            self._worker_started = True

        def _worker_loop() -> None:
            while True:
                try:
                    job_id, item_id = self._local_queue.get(timeout=2.0)
                except queue.Empty:
                    continue
                try:
                    self.process_job_item(job_id, item_id)
                except Exception:
                    pass
                finally:
                    self._local_queue.task_done()

        t = threading.Thread(
            target=_worker_loop, name="akkord-async-job-worker", daemon=True
        )
        t.start()

    def _build_oauth_credentials(self, oauth_tokens: dict[str, str]) -> Any:
        if not oauth_tokens or not oauth_tokens.get("access_token"):
            return None
        try:
            from google.oauth2.credentials import Credentials

            return Credentials(
                token=oauth_tokens.get("access_token"),
                refresh_token=oauth_tokens.get("refresh_token") or None,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=oauth_tokens.get("client_id") or DEFAULT_OAUTH_CLIENT_ID,
                client_secret=oauth_tokens.get("client_secret")
                or DEFAULT_OAUTH_CLIENT_SECRET,
            )
        except Exception:
            return None

    def process_job_item(
        self, job_id: str, item_id: str, force: bool = False
    ) -> dict[str, Any]:
        """Process a single PDF item in isolation and free all memory buffers afterwards."""
        job = self.get_job(job_id, reload_from_gcs=self.gcs.enabled)
        if job is None:
            return {"processed": False, "reason": "job_not_found"}

        item = next((it for it in job.items if it.item_id == item_id), None)
        if item is None:
            return {"processed": False, "reason": "item_not_found"}

        if not force and (
            job.status == "cancelled"
            or item.status == "cancelled"
            or self.activity_manager.is_cancelled()
        ):
            item.status = "cancelled"
            item.stage = "done"
            item.stage_message = "Annulé par l'utilisateur."
            self._save_job(job)
            return {"processed": False, "reason": "cancelled"}

        was_already_completed = item.status in ("completed", "skipped")
        if not force and was_already_completed:
            return {"processed": True, "reason": "already_completed"}

        # Check daily 25-file quota right before processing (unless force re-processing)
        if not force and not self.activity_manager.can_process_more_today():
            sched_dt = self._compute_schedule_for_excess_item(0)
            item.status = "deferred_next_day"
            item.scheduled_for = sched_dt.isoformat(timespec="minutes")
            item.stage = "deferred"
            item.stage_message = (
                f"Reporté automatiquement au {item.scheduled_for[:10]} "
                f"(quota quotidien de {DAILY_FILE_LIMIT} fichiers atteint)."
            )
            self._save_job(job)
            return {"processed": False, "reason": "deferred_next_day", "scheduled_for": item.scheduled_for}

        stage_weights = {
            "download": 15,
            "layout": 35,
            "harmony": 70,
            "annotate": 90,
            "upload": 95,
            "done": 100,
        }

        item.status = "processing"
        item.stage = "download"
        item.stage_message = f"Lecture / téléchargement de {item.filename}…"
        item.percent = 15
        self._save_job(job, preserve_item_id=item.item_id)

        def on_progress(stage: str, msg: str) -> None:
            item.stage = stage
            item.stage_message = msg
            item.percent = stage_weights.get(stage, 50)
            self._save_job(job, preserve_item_id=item.item_id)

        # Use an isolated temporary working directory for this single PDF and purge it in `finally`
        temp_work_dir = Path(tempfile.mkdtemp(prefix="akkord_item_"))
        try:
            config = AkkordConfig(
                model=job.model,
                language=job.language,
                output_dir=self.storage_dir,
                upload_to_drive=job.upload_to_drive,
            )
            oauth_creds = self._build_oauth_credentials(job.oauth_tokens)
            pipeline = AkkordPipeline(config, oauth_credentials=oauth_creds)

            local_pdf_path: Path | None = None
            if item.local_path and Path(item.local_path).is_file():
                local_pdf_path = Path(item.local_path)
            elif item.gcs_original_key:
                raw_orig = self.gcs.read_bytes(item.gcs_original_key)
                if raw_orig:
                    local_pdf_path = temp_work_dir / Path(item.filename).name
                    local_pdf_path.write_bytes(raw_orig)

            sheet = SheetFile(
                id=item.drive_file_id or item.filename,
                name=item.filename,
                source=item.source,
                local_path=local_pdf_path,
                drive_folder_id=item.drive_folder_id or None,
            )

            report = pipeline.process_single_pdf(
                sheet, work_dir=temp_work_dir, progress_callback=on_progress
            )
            rep_dict = pipeline.report_to_dict(report)

            # Persist original PDF to GCS/uploads under job-scoped namespace for private on-demand preview
            safe_orig_name = Path(item.filename).name
            orig_bytes: bytes | None = None
            if sheet.local_path and sheet.local_path.is_file():
                orig_bytes = sheet.local_path.read_bytes()
            if orig_bytes:
                # Keep local copy only when GCS is not active (so Cloud Run /tmp stays clean)
                self.gcs.write_bytes(
                    f"jobs/{job.job_id}/originals/{safe_orig_name}",
                    orig_bytes,
                    content_type="application/pdf",
                    keep_local_copy=not self.gcs.enabled,
                )
                uploads_dir = self.storage_dir / "_uploads"
                job_uploads_dir = uploads_dir / job.job_id
                if not self.gcs.enabled:
                    job_uploads_dir.mkdir(parents=True, exist_ok=True)
                    (job_uploads_dir / safe_orig_name).write_bytes(orig_bytes)
                elif (uploads_dir / safe_orig_name).is_file():
                    try:
                        (uploads_dir / safe_orig_name).unlink()
                    except Exception:
                        pass
                rep_dict["original_url"] = (
                    f"/api/jobs/{job.job_id}/originals/{quote(safe_orig_name)}"
                )
                item.original_url = rep_dict["original_url"]

            if report.output_filename and report.output_pdf_path:
                out_path = Path(report.output_pdf_path)
                if out_path.is_file():
                    out_bytes = out_path.read_bytes()
                    self.gcs.write_bytes(
                        f"jobs/{job.job_id}/outputs/{report.output_filename}",
                        out_bytes,
                        content_type="application/pdf",
                        keep_local_copy=not self.gcs.enabled,
                    )
                    if not self.gcs.enabled:
                        job_out_dir = self.storage_dir / "jobs" / job.job_id / "outputs"
                        job_out_dir.mkdir(parents=True, exist_ok=True)
                        (job_out_dir / report.output_filename).write_bytes(out_bytes)
                    else:
                        try:
                            out_path.unlink()
                        except Exception:
                            pass
                rep_dict["download_url"] = (
                    f"/api/jobs/{job.job_id}/outputs/{quote(report.output_filename)}"
                )
                item.output_filename = report.output_filename
                item.download_url = rep_dict["download_url"]

            effective_owner_id = normalize_record_owner_id(job.owner_id, job.user_email)
            if not was_already_completed:
                self.activity_manager.record_analysis(
                    rep_dict,
                    user_email=job.user_email,
                    source=item.source,
                    owner_id=effective_owner_id,
                )

            item.status = "completed" if report.is_music_sheet else "skipped"
            item.stage = "done"
            item.stage_message = f"Terminé : {item.output_filename or item.filename}"
            item.percent = 100
            item.report = rep_dict
            self._save_job(job, preserve_item_id=item.item_id)
            return {"processed": True, "status": item.status, "item_id": item.item_id}

        except Exception as exc:
            err_msg = str(exc)
            err_rep = {
                "source_name": item.filename,
                "source_id": item.drive_file_id or item.filename,
                "mode": "error",
                "error": err_msg,
            }
            self.activity_manager.record_analysis(
                err_rep,
                user_email=job.user_email,
                source=item.source,
                owner_id=normalize_record_owner_id(job.owner_id, job.user_email),
            )
            item.status = "error"
            item.stage = "done"
            item.stage_message = f"Erreur : {err_msg[:120]}"
            item.error = err_msg
            item.percent = 100
            item.report = err_rep
            self._save_job(job)
            return {"processed": False, "status": "error", "error": err_msg}
        finally:
            shutil.rmtree(temp_work_dir, ignore_errors=True)
            gc.collect()

    def cancel_job(
        self, job_id: str | None = None, owner_id: str | None = None
    ) -> BatchJob | None:
        """Cancel a specific job (or the most recent active job owned by `owner_id`) and mark queued/deferred items cancelled."""
        self.activity_manager.request_cancel()
        with self._lock:
            target: BatchJob | None = None
            if job_id:
                cand = self.get_job(job_id)
                if cand is not None and (
                    owner_id is None or self.job_belongs_to_owner(cand, owner_id)
                ):
                    target = cand
            else:
                active = [
                    j
                    for j in self._jobs.values()
                    if j.status in ("running", "partially_deferred")
                    and (owner_id is None or self.job_belongs_to_owner(j, owner_id))
                ]
                if active:
                    active.sort(key=lambda j: j.created_at, reverse=True)
                    target = active[0]
            if target is None:
                return None

            for it in target.items:
                if it.status in ("queued", "deferred_next_day", "processing"):
                    it.status = "cancelled"
                    it.stage = "done"
                    it.stage_message = "Annulé par l'utilisateur."
            target.status = "cancelled"
            self._save_job(target)
            return target

    def claim_anonymous_jobs(
        self, anon_owner_id: str, user_email: str, is_admin: bool = False
    ) -> int:
        """Transfer ownership of any jobs created under `anon_owner_id` in this browser tab to the newly logged-in Google user."""
        cleaned_anon = (anon_owner_id or "").strip()
        cleaned_email = (user_email or "").strip()
        if not cleaned_anon or not cleaned_email:
            return 0
        target_owner = f"user:{cleaned_email.lower()}"
        claimed_count = 0
        with self._lock:
            for job in list(self._jobs.values()):
                if self.job_belongs_to_owner(job, cleaned_anon):
                    job.owner_id = target_owner
                    job.user_email = cleaned_email
                    job.is_admin = is_admin
                    self._save_job(job)
                    claimed_count += 1
        try:
            self.activity_manager.claim_anonymous_entries(cleaned_anon, cleaned_email)
        except Exception:
            pass
        return claimed_count

    def resume_deferred_jobs(self, process_immediately_if_local: bool = False) -> dict[str, Any]:
        """Promote up to today's remaining quota (25 files/day) of `deferred_next_day` items to `queued` and dispatch them."""
        self.activity_manager.reset_cancel()
        quota = self.activity_manager.get_quota_status()
        remaining = int(quota.get("remaining", 0))
        if remaining <= 0:
            return {
                "resumed_count": 0,
                "remaining_quota": 0,
                "reason": "Quota quotidien déjà atteint pour aujourd'hui.",
            }

        resumed_items: list[tuple[str, str]] = []
        affected_jobs: list[BatchJob] = []

        with self._lock:
            # Reload jobs from GCS if enabled
            if self.gcs.enabled:
                self._load_existing_jobs()

            jobs_chronological = sorted(self._jobs.values(), key=lambda j: j.created_at)
            for job in jobs_chronological:
                if remaining <= 0:
                    break
                if job.status == "cancelled":
                    continue
                job_modified = False
                for it in job.items:
                    if remaining <= 0:
                        break
                    if it.status == "deferred_next_day":
                        it.status = "queued"
                        it.stage = "download"
                        it.stage_message = "Reprise automatique du quota quotidien…"
                        resumed_items.append((job.job_id, it.item_id))
                        remaining -= 1
                        job_modified = True
                if job_modified:
                    self._save_job(job)
                    affected_jobs.append(job)

        for job_id, item_id in resumed_items:
            if process_immediately_if_local and not self.cloud_tasks_enabled:
                self.process_job_item(job_id, item_id)
            elif self.cloud_tasks_enabled:
                job = self.get_job(job_id)
                if job:
                    self._enqueue_single_cloud_task(job_id, item_id)
            else:
                self._start_local_worker_if_needed()
                self._local_queue.put((job_id, item_id))

        return {
            "resumed_count": len(resumed_items),
            "remaining_quota": self.activity_manager.get_quota_status().get("remaining", 0),
            "jobs_updated": [j.job_id for j in affected_jobs],
        }

    def _enqueue_single_cloud_task(self, job_id: str, item_id: str) -> bool:
        token = self.gcs._get_token()
        if not token:
            return False
        queue_path = (
            f"projects/{DEFAULT_GCP_PROJECT}/locations/{DEFAULT_GCP_LOCATION}/"
            f"queues/{DEFAULT_TASKS_QUEUE}"
        )
        api_url = f"https://cloudtasks.googleapis.com/v2/{queue_path}/tasks"
        target_url = f"{DEFAULT_SERVICE_URL.rstrip('/')}/api/internal/tasks/process-file"
        body_bytes = json.dumps({"job_id": job_id, "item_id": item_id}).encode("utf-8")
        task_obj = {
            "httpRequest": {
                "httpMethod": "POST",
                "url": target_url,
                "headers": {"Content-Type": "application/json"},
                "body": base64.b64encode(body_bytes).decode("ascii"),
            }
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    api_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={"task": task_obj},
                )
                return resp.status_code in (200, 201)
        except Exception:
            return False

    def build_job_zip_bytes(self, job_id: str) -> tuple[bytes, str] | None:
        """Build an in-memory ZIP archive containing all completed annotated PDFs for a job."""
        job = self.get_job(job_id, reload_from_gcs=self.gcs.enabled)
        if job is None:
            return None

        buf = io.BytesIO()
        added_count = 0
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for it in job.items:
                if not it.output_filename:
                    continue
                pdf_bytes = self.read_output_pdf(it.output_filename, job_id=job.job_id)
                if pdf_bytes:
                    zf.writestr(it.output_filename, pdf_bytes)
                    added_count += 1

        if added_count == 0:
            return None
        zip_name = f"akkord-{job_id}-partitions-annotees.zip"
        return buf.getvalue(), zip_name

    def read_output_pdf(self, filename: str, job_id: str | None = None) -> bytes | None:
        safe_name = Path(filename).name
        if job_id:
            job_local = (self.storage_dir / "jobs" / job_id / "outputs" / safe_name).resolve()
            if job_local.is_file():
                return job_local.read_bytes()
            job_gcs = self.gcs.read_bytes(f"jobs/{job_id}/outputs/{safe_name}")
            if job_gcs:
                return job_gcs
        local_candidate = (self.storage_dir / safe_name).resolve()
        if local_candidate.is_file():
            return local_candidate.read_bytes()
        return self.gcs.read_bytes(f"outputs/{safe_name}")

    def read_original_pdf(self, filename: str, job_id: str | None = None) -> bytes | None:
        safe_name = Path(filename).name
        if job_id:
            job_local = (self.storage_dir / "_uploads" / job_id / safe_name).resolve()
            if job_local.is_file():
                return job_local.read_bytes()
            job_gcs = self.gcs.read_bytes(f"jobs/{job_id}/originals/{safe_name}")
            if job_gcs:
                return job_gcs
        local_candidate = (self.storage_dir / "_uploads" / safe_name).resolve()
        if local_candidate.is_file():
            return local_candidate.read_bytes()
        return self.gcs.read_bytes(f"originals/{safe_name}")

    def user_owns_filename(
        self, owner_id: str, filename: str, is_original: bool = False
    ) -> bool:
        """Verify whether `owner_id` owns any job or activity record referencing `filename`."""
        if not owner_id:
            return False
        safe_name = Path(filename).name
        for job in self.list_jobs(limit=200, owner_id=owner_id):
            for it in job.items:
                if is_original:
                    if Path(it.filename).name == safe_name:
                        return True
                else:
                    if Path(it.output_filename).name == safe_name:
                        return True
                    rep = it.report or {}
                    if Path(str(rep.get("output_filename") or "")).name == safe_name:
                        return True

        try:
            self.activity_manager.get_today_record()
            with self.activity_manager._lock:
                records = list(self.activity_manager._records.values())
            for rec in records:
                for entry in rec.entries:
                    entry_owner = normalize_record_owner_id(
                        getattr(entry, "owner_id", ""), entry.user_email
                    )
                    if entry_owner != owner_id:
                        continue
                    if is_original and Path(entry.filename).name == safe_name:
                        return True
                    if not is_original and Path(entry.output_filename).name == safe_name:
                        return True
        except Exception:
            pass
        return False
