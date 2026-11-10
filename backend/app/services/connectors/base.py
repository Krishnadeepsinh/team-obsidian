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
    ) -> requests.Response:
        """Perform HTTP call with rate-limit (429 / X-RateLimit-Reset) and transient 5xx retries."""
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

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        raise ConnectorError(f"OAuth authorization is not configured for {cls.provider_name}.")

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        raise ConnectorError(f"OAuth token exchange is not configured for {cls.provider_name}.")

