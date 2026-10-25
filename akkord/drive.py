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
"""Google Drive folder scanner, PDF downloader, and uploader (plus local folder support)."""

from __future__ import annotations

import html
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

GENERATED_SUFFIXES = (
    "-avec-accords.pdf",
    "-analyse-accords.pdf",
    "-with-chords.pdf",
    "-chord-analysis.pdf",
    "-annotated.pdf",
)

DRIVE_FOLDER_PATTERNS = (
    re.compile(r"drive\.google\.com/drive/(?:u/\d+/)?folders/([a-zA-Z0-9_-]+)"),
    re.compile(r"drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"),
    re.compile(r"^([a-zA-Z0-9_-]{15,60})$"),
)


@dataclass
class SheetFile:
    """Metadata for a discovered PDF file (from Google Drive or local disk)."""

    id: str
    name: str
    source: str  # "drive" or "local"
    local_path: Path | None = None
    drive_folder_id: str | None = None
    web_view_link: str | None = None


def is_generated_output(filename: str) -> bool:
    """Return True if filename matches one of Akord's generated PDF suffixes."""
    lower = filename.lower()
    return any(lower.endswith(suffix) for suffix in GENERATED_SUFFIXES)


def extract_folder_id(folder_input: str) -> str | None:
    """Extract a Google Drive folder ID from a URL or raw ID string.

    Returns None if folder_input points to an existing local path.
    """
    cleaned = folder_input.strip()
    if not cleaned:
        return None
    if Path(cleaned).exists():
        return None
    for pattern in DRIVE_FOLDER_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return match.group(1)
    return None


class DriveConnector:
    """Connects to Google Drive (authenticated via OAuth/Service Account or public shared folder) or local folders."""

    def __init__(
        self,
        credentials_path: str | None = None,
        api_key: str | None = None,
        oauth_credentials: Any = None,
    ) -> None:
        self.credentials_path = credentials_path or os.environ.get(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )
        self.drive_api_key = api_key or os.environ.get("GOOGLE_DRIVE_API_KEY")
        self.oauth_credentials = oauth_credentials
        self._service: Any = None

    def _get_oauth_access_token(self, force_refresh: bool = False) -> str | None:
        """Return a valid OAuth 2.0 access token from self.oauth_credentials, refreshing if needed."""
        creds = self.oauth_credentials
        if creds is None:
            return None
        token = getattr(creds, "token", None)
        refresh_token = getattr(creds, "refresh_token", None)
        client_id = getattr(creds, "client_id", None)
        client_secret = getattr(creds, "client_secret", None)
        token_uri = getattr(creds, "token_uri", None) or "https://oauth2.googleapis.com/token"

        if (force_refresh or not token) and refresh_token and client_id and client_secret:
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(
                        token_uri,
                        data={
                            "client_id": client_id,
                            "client_secret": client_secret,
                            "refresh_token": refresh_token,
                            "grant_type": "refresh_token",
                        },
                    )
                    if resp.status_code == 200:
                        new_token = resp.json().get("access_token")
                        if new_token:
                            creds.token = new_token
                            return new_token
            except Exception:
                pass
        return token

    def _drive_api_get(
        self, url: str, params: dict[str, Any] | None = None
    ) -> httpx.Response | None:
        """Perform an authenticated GET request to Google Drive v3 API using OAuth token (with auto-refresh)."""
        token = self._get_oauth_access_token(force_refresh=False)
        if not token:
            return None
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {token}"},
            )
            if resp.status_code == 401:
                refreshed = self._get_oauth_access_token(force_refresh=True)
                if refreshed and refreshed != token:
                    resp = client.get(
                        url,
                        params=params,
                        headers={"Authorization": f"Bearer {refreshed}"},
                    )
            return resp

    def _list_folder_via_oauth_http(self, folder_id: str) -> tuple[list[SheetFile], str | None]:
        """List PDFs (including shortcuts and 1st-level subfolders) using the user's OAuth token via REST."""
        token = self._get_oauth_access_token()
        if not token:
            return [], None

        url = "https://www.googleapis.com/drive/v3/files"

        def query_children(parent_id: str) -> tuple[list[dict[str, Any]], str | None]:
            all_files: list[dict[str, Any]] = []
            page_token: str | None = None
            while True:
                params: dict[str, Any] = {
                    "q": f"'{parent_id}' in parents and trashed = false",
                    "fields": "nextPageToken, files(id, name, mimeType, webViewLink, shortcutDetails)",
                    "pageSize": 200,
                    "supportsAllDrives": "true",
                    "includeItemsFromAllDrives": "true",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = self._drive_api_get(url, params=params)
                if resp is None:
                    return all_files, None
                if resp.status_code != 200:
                    try:
                        err_msg = resp.json().get("error", {}).get("message", resp.text)
                    except Exception:
                        err_msg = resp.text
                    return [], f"Google Drive API ({resp.status_code}): {err_msg}"
                body = resp.json()
                all_files.extend(body.get("files", []))
                page_token = body.get("nextPageToken")
                if not page_token or len(all_files) >= 1000:
                    break
            return all_files, None

        items, err = query_children(folder_id)
        if err:
            return [], err

        sheets: list[SheetFile] = []
        subfolders: list[str] = []
        seen_ids: set[str] = set()

        def collect_from_items(raw_items: list[dict[str, Any]], allow_subfolders: bool, current_folder: str = folder_id) -> None:
            for item in raw_items:
                mime = item.get("mimeType", "")
                name = item.get("name", "")
                fid = item.get("id", "")
                link = item.get("webViewLink")

                if mime == "application/vnd.google-apps.shortcut":
                    details = item.get("shortcutDetails") or {}
                    target_id = details.get("targetId")
                    target_mime = details.get("targetMimeType", "")
                    if target_id:
                        fid = target_id
                        mime = target_mime

                if (mime == "application/pdf" or name.lower().endswith(".pdf")) and fid:
                    if not name.lower().endswith(".pdf"):
                        name = f"{name}.pdf"
                    if not is_generated_output(name) and fid not in seen_ids:
                        seen_ids.add(fid)
                        sheets.append(
                            SheetFile(
                                id=fid,
                                name=name,
                                source="drive",
                                drive_folder_id=current_folder,
                                web_view_link=link or f"https://drive.google.com/file/d/{fid}/view",
                            )
                        )
                elif allow_subfolders and mime == "application/vnd.google-apps.folder" and fid:
                    subfolders.append(fid)

        collect_from_items(items, allow_subfolders=True, current_folder=folder_id)

        # Scan 1st-level subfolders as well so folders organized into subfolders are fully discovered
        if subfolders:
            for sub_id in subfolders[:25]:
                sub_items, _ = query_children(sub_id)
                collect_from_items(sub_items, allow_subfolders=False, current_folder=sub_id)

        return sheets, None

    def browse_drive_folder(
        self, folder_id: str = "root", search_query: str = ""
    ) -> dict[str, Any]:
        """Browse folders and PDFs inside the user's Google Drive via OAuth 2.0."""
        token = self._get_oauth_access_token()
        if not token:
            raise ValueError(
                "Veuillez d'abord vous connecter avec Google Drive pour parcourir vos dossiers."
            )

        url = "https://www.googleapis.com/drive/v3/files"
        cleaned_fid = (folder_id or "root").strip()
        cleaned_q = (search_query or "").strip()

        if cleaned_q:
            safe_q = cleaned_q.replace("\\", "\\\\").replace("'", "\\'")
            q_str = (
                f"mimeType = 'application/vnd.google-apps.folder' "
                f"and name contains '{safe_q}' and trashed = false"
            )
            current_meta = {"id": "search", "name": f"Recherche : « {cleaned_q} »"}
        elif cleaned_fid == "shared":
            q_str = "sharedWithMe = true and trashed = false"
            current_meta = {"id": "shared", "name": "Partagés avec moi"}
        else:
            q_str = f"'{cleaned_fid}' in parents and trashed = false"
            current_meta = {"id": "root", "name": "Mon Drive"}
            if cleaned_fid != "root":
                meta_resp = self._drive_api_get(
                    f"https://www.googleapis.com/drive/v3/files/{cleaned_fid}",
                    params={"fields": "id,name", "supportsAllDrives": "true"},
                )
                if meta_resp is not None and meta_resp.status_code == 200:
                    mdata = meta_resp.json()
                    current_meta = {
                        "id": mdata.get("id", cleaned_fid),
                        "name": mdata.get("name", "Dossier"),
                    }
                else:
                    current_meta = {"id": cleaned_fid, "name": "Dossier sélectionné"}

        params = {
            "q": q_str,
            "fields": "files(id, name, mimeType, shortcutDetails)",
            "orderBy": "folder,name",
            "pageSize": 200,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        resp = self._drive_api_get(url, params=params)
        if resp is None or resp.status_code != 200:
            err_detail = resp.text if resp is not None else "Pas de réponse"
            try:
                if resp is not None:
                    err_detail = resp.json().get("error", {}).get("message", resp.text)
            except Exception:
                pass
            raise ValueError(
                f"Erreur Google Drive API ({resp.status_code if resp else 'N/A'}) : {err_detail}"
            )

        raw_files = resp.json().get("files", [])
        folders: list[dict[str, str]] = []
        pdfs: list[dict[str, str]] = []
        seen_folders: set[str] = set()
        seen_pdfs: set[str] = set()

        for item in raw_files:
            mime = item.get("mimeType", "")
            name = item.get("name", "")
            fid = item.get("id", "")
            if mime == "application/vnd.google-apps.shortcut":
                details = item.get("shortcutDetails") or {}
                fid = details.get("targetId") or fid
                mime = details.get("targetMimeType") or mime

            if not fid:
                continue
            if mime == "application/vnd.google-apps.folder":
                if fid not in seen_folders:
                    seen_folders.add(fid)
                    folders.append({"id": fid, "name": name})
            elif mime == "application/pdf" or name.lower().endswith(".pdf"):
                if not is_generated_output(name) and fid not in seen_pdfs:
                    seen_pdfs.add(fid)
                    pdfs.append(
                        {
                            "id": fid,
                            "name": name if name.lower().endswith(".pdf") else f"{name}.pdf",
                        }
                    )

        return {
            "current_folder": current_meta,
            "folders": folders,
            "pdfs": pdfs,
            "pdf_count": len(pdfs),
        }

    def _get_drive_service(self) -> Any:
        """Build an authenticated Google Drive API v3 service if credentials exist."""
        if self._service is not None:
            return self._service

        try:
            from google.oauth2 import service_account
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request
            from googleapiclient.discovery import build
        except ImportError:
            return None

        scopes = ["https://www.googleapis.com/auth/drive"]
        creds = self.oauth_credentials

        if creds is not None and getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            try:
                creds.refresh(Request())
            except Exception:
                pass

        # 1. Service account JSON or authorized user JSON in credentials_path
        if creds is None and self.credentials_path and Path(self.credentials_path).is_file():
            try:
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path, scopes=scopes
                )
            except Exception:
                try:
                    creds = Credentials.from_authorized_user_file(
                        self.credentials_path, scopes
                    )
                except Exception:
                    creds = None

        # 2. Local token.json / credentials.json OAuth flow
        if creds is None and Path("token.json").is_file():
            try:
                creds = Credentials.from_authorized_user_file("token.json", scopes)
            except Exception:
                creds = None

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if creds is None and Path("credentials.json").is_file():
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", scopes)
            creds = flow.run_local_server(port=0)
            Path("token.json").write_text(creds.to_json(), encoding="utf-8")

        if creds is not None:
            self._service = build("drive", "v3", credentials=creds)
            return self._service

        # 3. Default Application Credentials fallback
        try:
            import google.auth

            default_creds, _ = google.auth.default(scopes=scopes)
            self._service = build("drive", "v3", credentials=default_creds)
            return self._service
        except Exception:
            return None

    def list_pdfs(self, folder_or_path: str) -> list[SheetFile]:
        """List all music sheet candidate PDFs in a local path or Google Drive folder."""
        path_obj = Path(folder_or_path.strip())
        if path_obj.exists():
            if path_obj.is_file() and path_obj.suffix.lower() == ".pdf":
                return [
                    SheetFile(
                        id=path_obj.name,
                        name=path_obj.name,
                        source="local",
                        local_path=path_obj.resolve(),
                    )
                ]
            if path_obj.is_dir():
                files: list[SheetFile] = []
                for p in sorted(path_obj.glob("*.pdf")):
                    if not is_generated_output(p.name):
                        files.append(
                            SheetFile(
                                id=p.name,
                                name=p.name,
                                source="local",
                                local_path=p.resolve(),
                            )
                        )
                return files

        folder_id = extract_folder_id(folder_or_path)
        if not folder_id:
            raise ValueError(
                f"Could not resolve '{folder_or_path}' as a local path or Google Drive folder ID/URL."
            )

        # 1. Try direct OAuth 2.0 user token REST API first (handles token refresh, shortcuts, and subfolders)
        oauth_error: str | None = None
        if self.oauth_credentials is not None:
            oauth_sheets, oauth_error = self._list_folder_via_oauth_http(folder_id)
            if oauth_sheets:
                return oauth_sheets

        # 2. Try authenticated Drive API v3 client (service account or local token.json)
        service = self._get_drive_service()
        if service is not None:
            try:
                query = f"'{folder_id}' in parents and trashed = false"
                resp = (
                    service.files()
                    .list(
                        q=query,
                        fields="files(id, name, mimeType, webViewLink, shortcutDetails)",
                        pageSize=200,
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute()
                )
                items = resp.get("files", [])
                results_from_service: list[SheetFile] = []
                for item in items:
                    mime = item.get("mimeType", "")
                    name = item.get("name", "")
                    fid = item.get("id", "")
                    if mime == "application/vnd.google-apps.shortcut":
                        details = item.get("shortcutDetails") or {}
                        fid = details.get("targetId") or fid
                        mime = details.get("targetMimeType") or mime
                    if (mime == "application/pdf" or name.lower().endswith(".pdf")) and not is_generated_output(name):
                        results_from_service.append(
                            SheetFile(
                                id=fid,
                                name=name if name.lower().endswith(".pdf") else f"{name}.pdf",
                                source="drive",
                                drive_folder_id=folder_id,
                                web_view_link=item.get("webViewLink"),
                            )
                        )
                if results_from_service:
                    return results_from_service
            except Exception:
                # Fall through to public folder scraping/API key mode
                pass

        # 3. Public folder fallback (via Drive API key or public HTML embedded view)
        public_sheets = self._list_public_drive_folder(folder_id)
        if public_sheets:
            return public_sheets

        if oauth_error:
            raise ValueError(oauth_error)
        return []

    def _list_public_drive_folder(self, folder_id: str) -> list[SheetFile]:
        """List PDFs from a publicly shared Google Drive folder without OAuth."""
        results: list[SheetFile] = []

        # Attempt 1: Public REST call with API key if provided
        if self.drive_api_key:
            url = "https://www.googleapis.com/drive/v3/files"
            params = {
                "q": f"'{folder_id}' in parents and mimeType='application/pdf' and trashed=false",
                "fields": "files(id,name,webViewLink)",
                "key": self.drive_api_key,
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            with httpx.Client(timeout=20.0, follow_redirects=True) as client:
                r = client.get(url, params=params)
                if r.status_code == 200:
                    for item in r.json().get("files", []):
                        if not is_generated_output(item["name"]):
                            results.append(
                                SheetFile(
                                    id=item["id"],
                                    name=item["name"],
                                    source="drive",
                                    drive_folder_id=folder_id,
                                    web_view_link=item.get("webViewLink"),
                                )
                            )
                    if results:
                        return results

        # Attempt 2: Public embedded folder view HTML parsing
        embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
        with httpx.Client(
            timeout=25.0,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        ) as client:
            resp = client.get(embed_url)
            if resp.status_code == 200:
                text = resp.text
                # Match entry-<id> blocks with flip-entry-title
                entry_pattern = re.compile(
                    r'id="entry-([a-zA-Z0-9_-]+)".*?class="flip-entry-title">([^<]+)</div>',
                    re.DOTALL,
                )
                for match in entry_pattern.finditer(text):
                    file_id = match.group(1)
                    name = html.unescape(match.group(2).strip())
                    if name.lower().endswith(".pdf") and not is_generated_output(name):
                        results.append(
                            SheetFile(
                                id=file_id,
                                name=name,
                                source="drive",
                                drive_folder_id=folder_id,
                                web_view_link=f"https://drive.google.com/file/d/{file_id}/view",
                            )
                        )
            if not results:
                # Also check standard folder page for ["<id>","<name>.pdf"] tuples
                folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
                resp2 = client.get(folder_url)
                if resp2.status_code == 200:
                    seen: set[str] = set()
                    # Look for PDF filenames near 25-44 char Drive IDs
                    for m in re.finditer(
                        r'"([a-zA-Z0-9_-]{25,44})"(?:[^"\n]{0,200}?)"([^"]+?\.pdf)"',
                        resp2.text,
                        re.IGNORECASE,
                    ):
                        fid, fname = m.group(1), html.unescape(m.group(2))
                        if fid != folder_id and fid not in seen and not is_generated_output(fname):
                            seen.add(fid)
                            results.append(
                                SheetFile(
                                    id=fid,
                                    name=fname,
                                    source="drive",
                                    drive_folder_id=folder_id,
                                    web_view_link=f"https://drive.google.com/file/d/{fid}/view",
                                )
                            )

        return results

    def download_pdf(self, sheet: SheetFile, dest_dir: Path) -> Path:
        """Download a SheetFile to dest_dir (or return local_path if already local)."""
        if sheet.local_path and sheet.local_path.is_file():
            return sheet.local_path

        dest_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(sheet.name).name
        target_path = dest_dir / safe_name

        if self.oauth_credentials is not None:
            resp = self._drive_api_get(
                f"https://www.googleapis.com/drive/v3/files/{sheet.id}",
                params={"alt": "media", "supportsAllDrives": "true"},
            )
            if resp is not None and resp.status_code == 200 and resp.content:
                target_path.write_bytes(resp.content)
                sheet.local_path = target_path
                return target_path

        service = self._get_drive_service()
        if service is not None:
            try:
                from googleapiclient.http import MediaIoBaseDownload

                request = service.files().get_media(
                    fileId=sheet.id, supportsAllDrives=True
                )
                buf = io.BytesIO()
                downloader = MediaIoBaseDownload(buf, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                target_path.write_bytes(buf.getvalue())
                sheet.local_path = target_path
                return target_path
            except Exception:
                pass

        # Public direct download fallback
        download_url = f"https://drive.google.com/uc?export=download&id={sheet.id}"
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            resp = client.get(download_url)
            resp.raise_for_status()
            target_path.write_bytes(resp.content)
            sheet.local_path = target_path
            return target_path

    def upload_pdf(
        self, local_pdf_path: Path, folder_id: str, remote_name: str | None = None
    ) -> dict[str, str] | None:
        """Upload an annotated PDF back to the target Google Drive folder."""
        filename = remote_name or local_pdf_path.name

        # 1. Try direct OAuth 2.0 multipart upload via httpx (thread-safe, avoids httplib2 crashes)
        if self.oauth_credentials is not None:
            token = self._get_oauth_access_token(force_refresh=False)
            if token:
                try:
                    boundary = "akkord_drive_multipart_boundary_987654"
                    meta_json = json.dumps(
                        {"name": filename, "parents": [folder_id]}
                    ).encode("utf-8")
                    pdf_bytes = local_pdf_path.read_bytes()
                    body = (
                        f"--{boundary}\r\n"
                        "Content-Type: application/json; charset=UTF-8\r\n\r\n"
                    ).encode("utf-8") + meta_json + (
                        f"\r\n--{boundary}\r\n"
                        "Content-Type: application/pdf\r\n\r\n"
                    ).encode("utf-8") + pdf_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

                    upload_url = "https://www.googleapis.com/upload/drive/v3/files"
                    params = {
                        "uploadType": "multipart",
                        "fields": "id,name,webViewLink",
                        "supportsAllDrives": "true",
                    }
                    headers = {
                        "Authorization": f"Bearer {token}",
                        "Content-Type": f"multipart/related; boundary={boundary}",
                    }
                    with httpx.Client(timeout=60.0) as client:
                        resp = client.post(upload_url, params=params, headers=headers, content=body)
                        if resp.status_code == 401:
                            refreshed = self._get_oauth_access_token(force_refresh=True)
                            if refreshed:
                                headers["Authorization"] = f"Bearer {refreshed}"
                                resp = client.post(
                                    upload_url, params=params, headers=headers, content=body
                                )
                        if resp.status_code in (200, 201):
                            created = resp.json()
                            fid = created.get("id", "")
                            web_link = created.get("webViewLink") or (
                                f"https://drive.google.com/file/d/{fid}/view" if fid else ""
                            )
                            return {
                                "id": fid,
                                "name": created.get("name", filename),
                                "webViewLink": web_link,
                            }
                except Exception:
                    pass

        # 2. Fallback to googleapiclient service
        service = self._get_drive_service()
        if service is None:
            return None

        from googleapiclient.http import MediaFileUpload

        metadata = {"name": filename, "parents": [folder_id]}
        media = MediaFileUpload(
            str(local_pdf_path), mimetype="application/pdf", resumable=False
        )
        created = (
            service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        fid = created.get("id", "")
        web_link = created.get("webViewLink") or (
            f"https://drive.google.com/file/d/{fid}/view" if fid else ""
        )
        return {
            "id": fid,
            "name": created.get("name", filename),
            "webViewLink": web_link,
        }
