import hashlib
import logging
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import requests

logger = logging.getLogger("team_obsidian.connectors")

_REFRESH_LOCKS: Dict[str, threading.Lock] = {}
_META_LOCK = threading.Lock()


def _get_integration_lock(integration_id: str) -> threading.Lock:
    with _META_LOCK:
        if integration_id not in _REFRESH_LOCKS:
            _REFRESH_LOCKS[integration_id] = threading.Lock()
        return _REFRESH_LOCKS[integration_id]


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

    Features:
    - Protects against concurrent refresh race conditions via per-integration locking.
    - Accurately distinguishes permanent tokens (PATs, Notion secrets, non-rotating Slack bots) vs refreshable OAuth tokens.
    - Supports GitHub App installation token generation with private key RS256 JWTs.
    - Preserves existing credentials and handles transient network errors without falsely marking tokens as revoked.
    - Marks status='token_expired' and auth_status='revoked' on permanent invalid_grant rejections.
    """
    from datetime import timedelta
    from app.core.security import decrypt_credentials, encrypt_credentials
    from app.services.connectors import get_connector_class

    if not integration or not getattr(integration, "credentials", None):
        return None

    integ_id = getattr(integration, "id", "anonymous")
    lock = _get_integration_lock(integ_id)

    with lock:
        # Re-read database state if db session provided to prevent duplicate refresh across threads
        if db and hasattr(integration, "id"):
            try:
                db.refresh(integration)
            except Exception:
                pass

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

        # Permanent tokens: no expiry and no refresh token or installation_id -> immediately valid
        refresh_token = creds.get("refresh_token")
        provider = getattr(integration, "provider", "")
        is_github_app = provider == "github" and bool(creds.get("installation_id"))

        if not refresh_token and not is_github_app and not token_expires_at:
            return current_token

        # If token has an expiry date that is still comfortably in the future (> 5 min), return it
        if current_token and token_expires_at and token_expires_at > (now_utc + timedelta(minutes=5)):
            return current_token

        # If it's a standard OAuth token without a refresh_token and expired, return current token
        if not refresh_token and not is_github_app:
            return current_token

        connector_cls = get_connector_class(provider)
        if not connector_cls:
            return current_token

        try:
            if is_github_app and hasattr(connector_cls, "create_installation_access_token"):
                new_bundle = connector_cls.create_installation_access_token(
                    installation_id=str(creds["installation_id"]),
                    app_id=creds.get("app_id"),
                    private_key=creds.get("private_key"),
                )
            elif refresh_token and hasattr(connector_cls, "refresh_oauth_token"):
                new_bundle = connector_cls.refresh_oauth_token(refresh_token)
            else:
                return current_token

            merged = {**creds, **new_bundle}
            integration.credentials = encrypt_credentials(merged)
            integration.error_message = None
            integration.status = "connected"
            integration.auth_status = "verified"
            if "expires_in" in new_bundle and new_bundle["expires_in"]:
                integration.token_expires_at = now_utc + timedelta(seconds=int(new_bundle["expires_in"]))
            elif "token_expires_at" in new_bundle and new_bundle["token_expires_at"]:
                exp = new_bundle["token_expires_at"]
                if isinstance(exp, str):
                    try:
                        integration.token_expires_at = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                    except Exception:
                        integration.token_expires_at = now_utc + timedelta(seconds=3600)
                elif isinstance(exp, datetime):
                    integration.token_expires_at = exp
            if db:
                db.commit()
                db.refresh(integration)
            return merged.get("access_token") or merged.get("token")
        except Exception as exc:
            err_str = str(exc).lower()
            # Distinguish transient network issues from permanent credential revocation
            is_transient = any(w in err_str for w in ["timeout", "connection refused", "failed to fetch", "502", "503", "504", "reset by peer"])
            logger.warning(
                "Failed to refresh token for integration %s (%s, transient=%s): %s",
                integ_id,
                provider,
                is_transient,
                exc,
            )
            if not is_transient:
                integration.status = "token_expired"
                integration.auth_status = "revoked"
                integration.error_message = f"Token revoked or refresh failed: {exc}"
            else:
                integration.error_message = f"Transient refresh warning: {exc}"

            if db:
                try:
                    db.commit()
                    db.refresh(integration)
                except Exception:
                    db.rollback()
            return current_token

