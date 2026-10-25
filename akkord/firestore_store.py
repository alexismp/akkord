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
"""Cloud Firestore persistence layer for Akkord (cost/token tracking, 25-file daily quota, sessions, and jobs)."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import threading
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

PARIS_TZ = ZoneInfo("Europe/Paris")
DEFAULT_GCP_PROJECT = (
    os.environ.get("GOOGLE_CLOUD_PROJECT")
    or os.environ.get("GCP_PROJECT")
    or "alexismp-runner"
)
DEFAULT_FIRESTORE_DB = os.environ.get("AKKORD_FIRESTORE_DB", "(default)")


def to_firestore_value(val: Any) -> dict[str, Any]:
    """Convert a Python value into a native Cloud Firestore REST API v1 Value object."""
    if val is None:
        return {"nullValue": None}
    if isinstance(val, bool):
        return {"booleanValue": val}
    if isinstance(val, int):
        return {"integerValue": str(val)}
    if isinstance(val, float):
        return {"doubleValue": float(val)}
    if isinstance(val, str):
        return {"stringValue": val}
    if isinstance(val, (list, tuple)):
        return {"arrayValue": {"values": [to_firestore_value(x) for x in val]}}
    if isinstance(val, dict):
        return {
            "mapValue": {
                "fields": {str(k): to_firestore_value(v) for k, v in val.items()}
            }
        }
    return {"stringValue": str(val)}


def from_firestore_value(v_obj: dict[str, Any]) -> Any:
    """Convert a Cloud Firestore REST API v1 Value object back into a native Python value."""
    if not isinstance(v_obj, dict):
        return v_obj
    if "nullValue" in v_obj:
        return None
    if "booleanValue" in v_obj:
        return bool(v_obj["booleanValue"])
    if "integerValue" in v_obj:
        try:
            return int(v_obj["integerValue"])
        except (ValueError, TypeError):
            return 0
    if "doubleValue" in v_obj:
        try:
            return float(v_obj["doubleValue"])
        except (ValueError, TypeError):
            return 0.0
    if "stringValue" in v_obj:
        return str(v_obj["stringValue"])
    if "timestampValue" in v_obj:
        return str(v_obj["timestampValue"])
    if "arrayValue" in v_obj:
        arr = v_obj["arrayValue"] or {}
        return [from_firestore_value(x) for x in arr.get("values", [])]
    if "mapValue" in v_obj:
        mp = v_obj["mapValue"] or {}
        return {
            k: from_firestore_value(val)
            for k, val in (mp.get("fields") or {}).items()
        }
    return None


def to_firestore_fields(doc_dict: dict[str, Any]) -> dict[str, Any]:
    """Convert a Python dict to Firestore Document `fields` map."""
    return {str(k): to_firestore_value(v) for k, v in doc_dict.items()}


def from_firestore_document(doc_payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a Firestore Document payload (`{"name": ..., "fields": {...}}`) to a Python dict."""
    fields = doc_payload.get("fields") or {}
    return {k: from_firestore_value(v) for k, v in fields.items()}


class FirestoreBackend:
    """Persistent Cloud Firestore backend (`projects/alexismp-runner/databases/(default)`) with SDK + REST + local mirror."""

    def __init__(
        self,
        local_dir: Path,
        project_id: str = DEFAULT_GCP_PROJECT,
        database_id: str = DEFAULT_FIRESTORE_DB,
    ) -> None:
        self.local_dir = local_dir
        self.local_dir.mkdir(parents=True, exist_ok=True)
        self.project_id = project_id
        self.database_id = database_id
        in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        explicit_flag = os.environ.get("AKKORD_ENABLE_FIRESTORE", "").strip().lower()
        if explicit_flag in ("0", "false", "no"):
            self.enabled = False
        elif explicit_flag in ("1", "true", "yes"):
            self.enabled = True
        else:
            self.enabled = bool(os.environ.get("K_SERVICE")) and not in_pytest
        self._creds: Any = None
        self._sdk_client: Any = None
        self._sdk_checked = False
        self._lock = threading.Lock()
        self._base_url = (
            f"https://firestore.googleapis.com/v1/projects/{self.project_id}/"
            f"databases/{quote(self.database_id, safe='()')}/documents"
        )

    def _get_sdk_client(self) -> Any:
        """Return official `google.cloud.firestore.Client` when available outside pytest."""
        if not self.enabled or os.environ.get("PYTEST_CURRENT_TEST"):
            return None
        with self._lock:
            if self._sdk_checked:
                return self._sdk_client
            self._sdk_checked = True
            try:
                from google.cloud import firestore  # type: ignore[import-untyped]

                self._sdk_client = firestore.Client(
                    project=self.project_id, database=self.database_id
                )
            except Exception:
                self._sdk_client = None
            return self._sdk_client

    def _get_token(self) -> str | None:
        if not self.enabled or os.environ.get("PYTEST_CURRENT_TEST"):
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

    def _local_doc_path(self, collection: str, doc_id: str) -> Path:
        safe_col = "".join(c if c.isalnum() or c in "-_" else "_" for c in collection)
        safe_id = "".join(c if c.isalnum() or c in "-_." else "_" for c in doc_id)
        p = self.local_dir / "_firestore_mirror" / safe_col / f"{safe_id}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def set_document(
        self, collection: str, doc_id: str, data: dict[str, Any]
    ) -> bool:
        """Create or overwrite a document in Cloud Firestore and update local mirror."""
        lp = self._local_doc_path(collection, doc_id)
        try:
            lp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass

        # 1. Official Firestore Python SDK
        sdk = self._get_sdk_client()
        if sdk is not None:
            try:
                sdk.collection(collection).document(doc_id).set(data)
                return True
            except Exception:
                pass

        # 2. Firestore REST API v1
        token = self._get_token()
        if not token:
            return True

        url = f"{self._base_url}/{quote(collection, safe='')}/{quote(doc_id, safe='')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {"fields": to_firestore_fields(data)}
        try:
            with httpx.Client(timeout=20.0) as client:
                resp = client.patch(url, headers=headers, json=payload)
                if resp.status_code == 403:
                    headers["x-goog-user-project"] = self.project_id
                    resp = client.patch(url, headers=headers, json=payload)
                return resp.status_code in (200, 201)
        except Exception:
            return False

    def get_document(
        self, collection: str, doc_id: str
    ) -> dict[str, Any] | None:
        """Read a single document from Cloud Firestore (falling back to local mirror)."""
        # 1. Official Firestore Python SDK
        sdk = self._get_sdk_client()
        if sdk is not None:
            try:
                snap = sdk.collection(collection).document(doc_id).get()
                if snap.exists:
                    doc = snap.to_dict() or {}
                    lp = self._local_doc_path(collection, doc_id)
                    try:
                        lp.write_text(
                            json.dumps(doc, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    return doc
                return None
            except Exception:
                pass

        # 2. Firestore REST API v1
        token = self._get_token()
        if token:
            url = f"{self._base_url}/{quote(collection, safe='')}/{quote(doc_id, safe='')}"
            headers = {"Authorization": f"Bearer {token}"}
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 403:
                        headers["x-goog-user-project"] = self.project_id
                        resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        doc = from_firestore_document(resp.json())
                        lp = self._local_doc_path(collection, doc_id)
                        try:
                            lp.write_text(
                                json.dumps(doc, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                        return doc
                    if resp.status_code == 404:
                        return None
            except Exception:
                pass

        lp = self._local_doc_path(collection, doc_id)
        if lp.is_file():
            try:
                return json.loads(lp.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def list_documents(
        self, collection: str, page_size: int = 200
    ) -> dict[str, dict[str, Any]]:
        """List all documents in a Firestore collection as `{doc_id: data_dict}`."""
        results: dict[str, dict[str, Any]] = {}

        # Read local mirror first as baseline
        col_dir = self._local_doc_path(collection, "dummy").parent
        if col_dir.is_dir():
            for f in sorted(col_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        doc_key = str(data.get("date") or data.get("job_id") or f.stem)
                        results[doc_key] = data
                except Exception:
                    pass

        # 1. Official Firestore Python SDK
        sdk = self._get_sdk_client()
        if sdk is not None:
            try:
                for snap in sdk.collection(collection).stream():
                    parsed = snap.to_dict() or {}
                    doc_id = snap.id
                    if doc_id:
                        results[doc_id] = parsed
                        lp = self._local_doc_path(collection, doc_id)
                        try:
                            lp.write_text(
                                json.dumps(parsed, indent=2, ensure_ascii=False),
                                encoding="utf-8",
                            )
                        except Exception:
                            pass
                return results
            except Exception:
                pass

        # 2. Firestore REST API v1
        token = self._get_token()
        if token:
            url = f"{self._base_url}/{quote(collection, safe='')}"
            headers = {"Authorization": f"Bearer {token}"}
            page_token: str | None = None
            try:
                with httpx.Client(timeout=20.0) as client:
                    while True:
                        params: dict[str, Any] = {"pageSize": page_size}
                        if page_token:
                            params["pageToken"] = page_token
                        resp = client.get(url, headers=headers, params=params)
                        if resp.status_code == 403:
                            headers["x-goog-user-project"] = self.project_id
                            resp = client.get(url, headers=headers, params=params)
                        if resp.status_code != 200:
                            break
                        body = resp.json()
                        for raw_doc in body.get("documents") or []:
                            name = str(raw_doc.get("name") or "")
                            doc_id = name.rsplit("/", 1)[-1] if "/" in name else name
                            parsed = from_firestore_document(raw_doc)
                            if doc_id:
                                results[doc_id] = parsed
                                lp = self._local_doc_path(collection, doc_id)
                                try:
                                    lp.write_text(
                                        json.dumps(parsed, indent=2, ensure_ascii=False),
                                        encoding="utf-8",
                                    )
                                except Exception:
                                    pass
                        page_token = body.get("nextPageToken")
                        if not page_token:
                            break
            except Exception:
                pass

        return results

    def delete_document(self, collection: str, doc_id: str) -> bool:
        lp = self._local_doc_path(collection, doc_id)
        if lp.is_file():
            try:
                lp.unlink()
            except Exception:
                pass
        sdk = self._get_sdk_client()
        if sdk is not None:
            try:
                sdk.collection(collection).document(doc_id).delete()
                return True
            except Exception:
                pass
        token = self._get_token()
        if not token:
            return True
        url = f"{self._base_url}/{quote(collection, safe='')}/{quote(doc_id, safe='')}"
        headers = {"Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.delete(url, headers=headers)
                if resp.status_code == 403:
                    headers["x-goog-user-project"] = self.project_id
                    resp = client.delete(url, headers=headers)
                return resp.status_code in (200, 204, 404)
        except Exception:
            return False

    @staticmethod
    def hash_session_id(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:40]
