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
"""Google OAuth 2.0 Web flow and session management for private Google Drive access and admin auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import httpx

from akkord.firestore_store import FirestoreBackend

ADMIN_EMAIL = "alexis.mp@gmail.com"

DEFAULT_OAUTH_CLIENT_ID = (
    "2500276981-gmjvvn9ucbagv4g44n7rsdq9qo688hpb.apps.googleusercontent.com"
)
DEFAULT_OAUTH_CLIENT_SECRET = os.environ.get(
    "GOOGLE_OAUTH_CLIENT_SECRET", "configured-via-env"
)
DEFAULT_OAUTH_REDIRECT_URI = (
    "https://akkord-2500276981.europe-west1.run.app/auth/callback"
)

OAUTH_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/gmail.send",
]

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v3/userinfo"


@dataclass
class UserSession:
    """Authenticated Google OAuth user session."""

    session_id: str
    email: str
    name: str
    picture: str
    access_token: str
    refresh_token: str | None
    token_uri: str = GOOGLE_TOKEN_ENDPOINT
    client_id: str = DEFAULT_OAUTH_CLIENT_ID
    client_secret: str = DEFAULT_OAUTH_CLIENT_SECRET

    @property
    def is_admin(self) -> bool:
        return self.email.strip().lower() == ADMIN_EMAIL

    def to_google_credentials(self) -> Any:
        """Build a google.oauth2.credentials.Credentials object for Google Drive API v3."""
        from google.oauth2.credentials import Credentials

        return Credentials(
            token=self.access_token,
            refresh_token=self.refresh_token,
            token_uri=self.token_uri,
            client_id=self.client_id or None,
            client_secret=self.client_secret or None,
            scopes=OAUTH_SCOPES,
        )


class OAuthManager:
    """Manages OAuth 2.0 Web Client flows and user sessions (configured strictly server-side)."""

    def __init__(
        self, storage_dir: Path, firestore_backend: FirestoreBackend | None = None
    ) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.sessions_file = self.storage_dir / "_oauth_sessions.json"
        self.firestore_backend = firestore_backend or FirestoreBackend(storage_dir)
        self._pending_states: dict[str, str] = {}
        self._sessions: dict[str, UserSession] = {}
        self._load_sessions()

    def get_client_credentials(self) -> tuple[str, str]:
        """Return (client_id, client_secret) configured server-side."""
        cid = (
            os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
            or os.environ.get("GOOGLE_CLIENT_ID")
            or DEFAULT_OAUTH_CLIENT_ID
        ).strip()
        csec = (
            os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
            or os.environ.get("GOOGLE_CLIENT_SECRET")
            or DEFAULT_OAUTH_CLIENT_SECRET
        ).strip()
        return cid, csec

    def is_configured(self) -> bool:
        cid, csec = self.get_client_credentials()
        return bool(cid and csec)

    def build_authorization_url(self, redirect_uri: str, intent: str = "") -> str:
        """Create the Google OAuth 2.0 authorization URL."""
        client_id, _ = self.get_client_credentials()
        if not client_id:
            raise ValueError("Google OAuth Client ID non configuré.")

        raw_state = secrets.token_urlsafe(24)
        state = f"{raw_state}:{intent.strip()}" if intent.strip() else raw_state
        self._pending_states[state] = redirect_uri

        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(OAUTH_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
        return f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(params)}"

    @staticmethod
    def extract_state_intent(state: str) -> str:
        """Extract optional intent suffix from OAuth `state` parameter."""
        if not state or ":" not in state:
            return ""
        return state.split(":", 1)[1].strip()

    def exchange_code_for_session(
        self, code: str, state: str, fallback_redirect_uri: str
    ) -> UserSession:
        """Exchange authorization code for access/refresh tokens and fetch user profile."""
        client_id, client_secret = self.get_client_credentials()
        if not client_id or not client_secret:
            raise ValueError("Identifiants OAuth non configurés.")

        redirect_uri = self._pending_states.pop(state, None) or fallback_redirect_uri

        with httpx.Client(timeout=20.0) as client:
            token_resp = client.post(
                GOOGLE_TOKEN_ENDPOINT,
                data={
                    "code": code,
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            if token_resp.status_code != 200:
                raise ValueError(
                    f"Échec de l'échange OAuth ({token_resp.status_code}): {token_resp.text}"
                )
            token_data = token_resp.json()
            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token")

            userinfo_resp = client.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                raise ValueError("Impossible de récupérer le profil Google OAuth.")
            profile = userinfo_resp.json()

        session_id = secrets.token_urlsafe(24)
        user_session = UserSession(
            session_id=session_id,
            email=profile.get("email", ""),
            name=profile.get("name", profile.get("email", "Utilisateur")),
            picture=profile.get("picture", ""),
            access_token=access_token,
            refresh_token=refresh_token,
            client_id=client_id,
            client_secret=client_secret,
        )
        signed_cookie = self.encode_session_cookie(user_session)
        user_session.session_id = signed_cookie
        self._sessions[signed_cookie] = user_session
        self._sessions[session_id] = user_session
        self._save_sessions()
        return user_session

    def _signing_key(self) -> bytes:
        _, csec = self.get_client_credentials()
        return (csec or DEFAULT_OAUTH_CLIENT_SECRET).encode("utf-8")

    def encode_session_cookie(self, s: UserSession) -> str:
        """Encode and HMAC-sign a UserSession so it survives Cloud Run scaling/restarts."""
        payload = {
            "e": s.email,
            "n": s.name,
            "p": s.picture,
            "a": s.access_token,
            "r": s.refresh_token,
        }
        raw_bytes = zlib.compress(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        b64_payload = base64.urlsafe_b64encode(raw_bytes).decode("ascii").rstrip("=")
        sig = hmac.new(
            self._signing_key(), b64_payload.encode("ascii"), hashlib.sha256
        ).hexdigest()[:32]
        return f"v1.{b64_payload}.{sig}"

    def decode_session_cookie(self, token: str) -> UserSession | None:
        """Verify and decode an HMAC-signed cookie value into a UserSession."""
        if not token or not token.startswith("v1."):
            return None
        parts = token.split(".")
        if len(parts) != 3:
            return None
        _, b64_payload, sig = parts
        expected_sig = hmac.new(
            self._signing_key(), b64_payload.encode("ascii"), hashlib.sha256
        ).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected_sig):
            return None
        try:
            pad = "=" * (-len(b64_payload) % 4)
            raw_bytes = zlib.decompress(base64.urlsafe_b64decode(b64_payload + pad))
            data = json.loads(raw_bytes.decode("utf-8"))
            cid, csec = self.get_client_credentials()
            return UserSession(
                session_id=token,
                email=data.get("e", ""),
                name=data.get("n", ""),
                picture=data.get("p", ""),
                access_token=data.get("a", ""),
                refresh_token=data.get("r"),
                client_id=cid,
                client_secret=csec,
            )
        except Exception:
            return None

    def get_session(self, session_id: str | None) -> UserSession | None:
        if not session_id:
            return None
        if session_id in self._sessions:
            return self._sessions[session_id]
        decoded = self.decode_session_cookie(session_id)
        if decoded is not None:
            self._sessions[session_id] = decoded
            return decoded
        try:
            doc_id = FirestoreBackend.hash_session_id(session_id)
            fs_doc = self.firestore_backend.get_document("akkord_sessions", doc_id)
            if isinstance(fs_doc, dict) and fs_doc.get("email"):
                cid, csec = self.get_client_credentials()
                s = UserSession(
                    session_id=session_id,
                    email=str(fs_doc.get("email") or ""),
                    name=str(fs_doc.get("name") or ""),
                    picture=str(fs_doc.get("picture") or ""),
                    access_token=str(fs_doc.get("access_token") or ""),
                    refresh_token=fs_doc.get("refresh_token") or None,
                    client_id=cid,
                    client_secret=csec,
                )
                self._sessions[session_id] = s
                return s
        except Exception:
            pass
        return None

    def delete_session(self, session_id: str | None) -> None:
        if not session_id:
            return
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._save_sessions()
        try:
            doc_id = FirestoreBackend.hash_session_id(session_id)
            self.firestore_backend.delete_document("akkord_sessions", doc_id)
        except Exception:
            pass

    def _load_sessions(self) -> None:
        if not self.sessions_file.is_file():
            return
        try:
            raw = json.loads(self.sessions_file.read_text(encoding="utf-8"))
            for sid, item in raw.items():
                self._sessions[sid] = UserSession(**item)
        except Exception:
            pass

    def _save_sessions(self) -> None:
        try:
            payload = {
                sid: {
                    "session_id": s.session_id,
                    "email": s.email,
                    "name": s.name,
                    "picture": s.picture,
                    "access_token": s.access_token,
                    "refresh_token": s.refresh_token,
                    "token_uri": s.token_uri,
                    "client_id": s.client_id,
                    "client_secret": s.client_secret,
                }
                for sid, s in self._sessions.items()
            }
            self.sessions_file.write_text(
                json.dumps(payload, indent=2), encoding="utf-8"
            )
            for sid, item in payload.items():
                doc_id = FirestoreBackend.hash_session_id(sid)
                self.firestore_backend.set_document("akkord_sessions", doc_id, item)
        except Exception:
            pass
