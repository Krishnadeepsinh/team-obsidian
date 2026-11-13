from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode
import requests

from app.core.config import settings
from app.services.connectors.base import BaseConnector, ConnectorError, compute_sha256, parse_iso_timestamp

logger = logging.getLogger("team_obsidian.connectors.google_drive")


class GoogleDriveConnector(BaseConnector):
    """Google Drive connector supporting OAuth 2.0, folder hierarchy discovery, document synchronization, and pagination."""

    provider_name: str = "google_drive"
    API_BASE = "https://www.googleapis.com/drive/v3"
    OAUTH_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
    OAUTH_REVOKE_URL = "https://oauth2.googleapis.com/revoke"

    def __init__(self, token: Optional[str] = None):
        super().__init__(token)

    def _headers(self) -> Dict[str, str]:
        if not self.token:
            raise ConnectorError("Google Drive authentication token is required.")
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }

    def check_connection(self) -> Dict[str, Any]:
        """Verify access by querying Drive user profile and quota."""
        res = self._request_with_retry(
            method="GET",
            url=f"{self.API_BASE}/about",
            headers=self._headers(),
            params={"fields": "user(displayName,emailAddress,permissionId),storageQuota"},
        )
        if res.status_code == 401:
            raise ConnectorError("Invalid or expired Google Drive access token.")
        if res.status_code != 200:
            raise ConnectorError(f"Google Drive verification failed with status {res.status_code}: {res.text}")

        data = res.json()
        user_info = data.get("user") or {}
        return {
            "status": "connected",
            "account_id": user_info.get("permissionId"),
            "account_name": user_info.get("displayName") or user_info.get("emailAddress"),
            "email": user_info.get("emailAddress"),
            "scopes": ["https://www.googleapis.com/auth/drive.readonly"],
            "storage_quota": data.get("storageQuota"),
        }

    def extract_data(
        self,
        resource_type: str,
        resource_id: str,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Extract files belonging to a specific folder or file ID with page-token cursor."""
        params: Dict[str, Any] = {
            "pageSize": min(max(1, limit), 100),
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size,webViewLink,owners,description)",
        }
        if cursor:
            params["pageToken"] = cursor
        if resource_type == "folder" and resource_id:
            params["q"] = f"'{resource_id}' in parents and trashed = false"
        else:
            params["q"] = "trashed = false"

        res = self._request_with_retry(
            method="GET",
            url=f"{self.API_BASE}/files",
            headers=self._headers(),
            params=params,
        )
        if res.status_code != 200:
            raise ConnectorError(f"Failed to extract Google Drive files: {res.text}")

        data = res.json()
        files = data.get("files") or []
        records = []
        for f in files:
            owner = (f.get("owners") or [{}])[0].get("displayName") or "Unknown"
            records.append({
                "source_record_id": f.get("id"),
                "source_type": "google_drive_file",
                "source_title": f.get("name") or "Untitled Document",
                "source_author": owner,
                "source_url": f.get("webViewLink"),
                "source_timestamp": parse_iso_timestamp(f.get("modifiedTime")) or datetime.now(timezone.utc),
                "content": f.get("description") or f"Google Drive File: {f.get('name')} ({f.get('mimeType')})",
                "metadata": {
                    "mime_type": f.get("mimeType"),
                    "size": f.get("size"),
                },
            })

        next_page = data.get("nextPageToken")
        return {
            "records": records,
            "next_cursor": next_page,
            "has_more": bool(next_page),
        }

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Synchronize files modified since sync_cursor."""
        cfg = config or {}
        cursor = sync_cursor or {}
        since_iso = cursor.get("last_sync_at")
        folder_id = cfg.get("folder_id")

        q_parts = ["trashed = false"]
        if folder_id:
            q_parts.append(f"'{folder_id}' in parents")
        if since_iso:
            q_parts.append(f"modifiedTime > '{since_iso}'")

        params: Dict[str, Any] = {
            "pageSize": min(int(cfg.get("limit", 50)), 100),
            "fields": "nextPageToken,files(id,name,mimeType,modifiedTime,size,webViewLink,owners,description)",
            "orderBy": "modifiedTime desc",
            "q": " and ".join(q_parts),
        }

        res = self._request_with_retry(
            method="GET",
            url=f"{self.API_BASE}/files",
            headers=self._headers(),
            params=params,
        )
        if res.status_code != 200:
            raise ConnectorError(f"Failed to sync Google Drive files: {res.text}")

        data = res.json()
        files = data.get("files") or []
        records: List[Dict[str, Any]] = []
        newest_ts = since_iso

        for f in files:
            mod_ts = f.get("modifiedTime")
            if mod_ts and (not newest_ts or mod_ts > newest_ts):
                newest_ts = mod_ts

            owner = (f.get("owners") or [{}])[0].get("displayName") or "Unknown"
            records.append({
                "source_record_id": f.get("id"),
                "source_type": "google_drive_file",
                "source_title": f.get("name") or "Google Drive Document",
                "source_author": owner,
                "source_url": f.get("webViewLink"),
                "source_timestamp": parse_iso_timestamp(mod_ts) or datetime.now(timezone.utc),
                "content": f.get("description") or f"Google Drive File: {f.get('name')}",
                "metadata": {
                    "mime_type": f.get("mimeType"),
                    "size": f.get("size"),
                },
            })

        updated_cursor = {
            "last_sync_at": newest_ts or datetime.now(timezone.utc).isoformat(),
            "next_page_token": data.get("nextPageToken"),
        }
        return records, updated_cursor

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange Google refresh token for a fresh access token."""
        client_id = settings.GOOGLE_DRIVE_CLIENT_ID
        client_secret = settings.GOOGLE_DRIVE_CLIENT_SECRET
        if not client_id or not client_secret:
            raise ConnectorError("Google Drive OAuth client credentials not configured.")

        res = self._request_with_retry(
            method="POST",
            url=self.OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if res.status_code != 200:
            raise ConnectorError(f"Failed to refresh Google Drive token: {res.text}")

        data = res.json()
        self.token = data.get("access_token")
        return {
            "access_token": self.token,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type", "Bearer"),
        }

    def disconnect(self) -> Dict[str, Any]:
        """Revoke Google OAuth token."""
        if self.token:
            try:
                self._request_with_retry(
                    method="POST",
                    url=self.OAUTH_REVOKE_URL,
                    params={"token": self.token},
                )
            except Exception as e:
                logger.warning("Google Drive token revocation error: %s", e)
        self.token = None
        return {"status": "disconnected", "provider": self.provider_name}

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        client_id = settings.GOOGLE_DRIVE_CLIENT_ID
        if not client_id:
            raise ConnectorError("GOOGLE_DRIVE_CLIENT_ID is not configured.")
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.readonly",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{cls.OAUTH_AUTH_URL}?{urlencode(params)}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        client_id = settings.GOOGLE_DRIVE_CLIENT_ID
        client_secret = settings.GOOGLE_DRIVE_CLIENT_SECRET
        if not client_id or not client_secret:
            raise ConnectorError("Google Drive OAuth client credentials not configured.")

        res = requests.post(
            cls.OAUTH_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
            timeout=15,
        )
        if res.status_code != 200:
            raise ConnectorError(f"Google Drive OAuth token exchange failed: {res.text}")
        return res.json()


google_drive_connector = GoogleDriveConnector()
