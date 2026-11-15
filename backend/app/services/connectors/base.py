import hashlib
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("team_obsidian.connectors")


def compute_sha256(content: str) -> str:
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return None


class ConnectorError(Exception):
    """Raised when a provider connector encounters an authentication or API error."""


class BaseConnector(ABC):
    """Unified provider connector interface for GitHub, Slack, Notion, and extensible sources."""

    provider_name: str = "base"

    def __init__(self, token: Optional[str] = None):
        self.token = token

    def _request_with_retry(
        self,
        method: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: int = 12,
        max_retries: int = 3,
        allow_redirects: bool = False,
    ) -> requests.Response:
        """Perform HTTP call with rate-limit (429 / X-RateLimit-Reset) and transient 5xx retries, preventing SSRF redirects."""
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                res = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    data=data,
                    timeout=timeout,
                    allow_redirects=allow_redirects,
                )
                if res.status_code == 429 or (
                    res.status_code == 403 and res.headers.get("X-RateLimit-Remaining") == "0"
                ):
                    retry_after = int(res.headers.get("Retry-After", "2") or "2")
                    sleep_sec = min(max(retry_after, 1), 10)
                    logger.warning("%s rate-limited (status=%s); sleeping %ss", self.provider_name, res.status_code, sleep_sec)
                    time.sleep(sleep_sec)
                    continue
                if res.status_code >= 500 and attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                return res
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < max_retries - 1:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise ConnectorError(f"{self.provider_name} network error: {exc}") from exc

        if last_exc:
            raise ConnectorError(f"{self.provider_name} request failed: {last_exc}")
        raise ConnectorError(f"{self.provider_name} rate limit exceeded after {max_retries} retries.")

    @abstractmethod
    def check_connection(self) -> Dict[str, Any]:
        """Verify live authentication and return account identity, scopes, and status."""

    @abstractmethod
    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Retrieve normalized records and return (records, updated_sync_cursor)."""

    def extract_data(
        self,
        resource_type: str,
        resource_id: str,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Granular data extraction with pagination for specific resource types. Default implementation delegates to sync."""
        records, next_cur = self.sync(config={"resource_type": resource_type, "resource_id": resource_id, "limit": limit})
        return {
            "records": records,
            "next_cursor": next_cur.get("cursor") or next_cur.get("last_sync_at"),
            "has_more": bool(next_cur.get("has_more", False)),
        }

    def refresh_token(self, refresh_token: str) -> Dict[str, Any]:
        """Refresh expired OAuth2 access token. Default raises if not applicable."""
        raise ConnectorError(f"Token refresh is not supported or configured for {self.provider_name}.")

    def disconnect(self) -> Dict[str, Any]:
        """Cleanly revoke credentials or disconnect integration session."""
        self.token = None
        return {"status": "disconnected", "provider": self.provider_name}

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        raise ConnectorError(f"OAuth authorization is not configured for {cls.provider_name}.")

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise ConnectorError(f"OAuth token exchange is not configured for {cls.provider_name}.")


def ensure_valid_token(integration: Any, db: Any = None) -> Optional[str]:
    """Ensure that integration credentials have a valid, active access token.
    If the token is expired or within 5 minutes of expiring, automatically refresh it
    using the provider's refresh mechanism and update the database record.
    """
    from datetime import timedelta
    from app.core.security import decrypt_credentials, encrypt_credentials
    from app.services.connectors import get_connector_class

    if not integration or not getattr(integration, "credentials", None):
        return None

    creds = decrypt_credentials(integration.credentials) if isinstance(integration.credentials, (dict, str)) else {}
    current_token = (
        creds.get("access_token")
        or creds.get("token")
        or creds.get("api_key")
        or creds.get("bot_token")
    )

    now_utc = datetime.now(timezone.utc)
    token_expires_at = getattr(integration, "token_expires_at", None)
    if token_expires_at and token_expires_at.tzinfo is None:
        token_expires_at = token_expires_at.replace(tzinfo=timezone.utc)

    # If token expires in more than 5 minutes, it is still valid
    if current_token and token_expires_at and token_expires_at > (now_utc + timedelta(minutes=5)):
        return current_token

    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return current_token

    connector_cls = get_connector_class(getattr(integration, "provider", ""))
    if not connector_cls or not hasattr(connector_cls, "refresh_oauth_token"):
        return current_token

    try:
        new_bundle = connector_cls.refresh_oauth_token(refresh_token)
        merged = {**creds, **new_bundle}
        integration.credentials = encrypt_credentials(merged)
        integration.error_message = None
        integration.status = "connected"
        integration.auth_status = "verified"
        if "expires_in" in new_bundle and new_bundle["expires_in"]:
            integration.token_expires_at = now_utc + timedelta(seconds=int(new_bundle["expires_in"]))
        if db:
            db.commit()
            db.refresh(integration)
        return merged.get("access_token") or merged.get("token")
    except Exception as exc:
        logger.warning(
            "Failed to refresh OAuth token for integration %s (%s): %s",
            getattr(integration, "id", "unknown"),
            getattr(integration, "provider", "unknown"),
            exc,
        )
        integration.status = "token_expired"
        integration.auth_status = "revoked"
        integration.error_message = f"Token expired or refresh failed: {exc}"
        if db:
            try:
                db.commit()
                db.refresh(integration)
            except Exception:
                db.rollback()
        return current_token

