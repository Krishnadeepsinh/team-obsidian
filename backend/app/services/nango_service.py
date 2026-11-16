from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger("team_obsidian.nango_service")


class NangoServiceError(Exception):
    """Raised when communication with Nango API fails."""
    pass


class NangoService:
    """
    Nango API client supporting:
    1. Connect Sessions (OAuth Connect UI session tokens and hosted links for Slack)
    2. Connection and credential retrieval for downstream connectors
    3. Revocation and disconnect management
    """

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = settings.NANGO_API_KEY if api_key is None else api_key
        self.base_url = (base_url or settings.NANGO_BASE_URL or "https://api.nango.dev").rstrip("/")
        self.slack_integration_id = settings.NANGO_SLACK_INTEGRATION_ID or "slack"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 8)

    def _headers(self) -> Dict[str, str]:
        if not self.is_configured:
            raise NangoServiceError("Nango API key is not configured. Set NANGO_API_KEY in backend/.env.")
        return {
            "Authorization": f"Bearer {self.api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_integrations(self) -> List[Dict[str, Any]]:
        """List all integrations configured in the Nango environment (e.g. Slack)."""
        url = f"{self.base_url}/integrations"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=self._headers())
                if res.status_code != 200:
                    raise NangoServiceError(f"Failed to fetch Nango integrations: HTTP {res.status_code} - {res.text}")
                data = res.json()
                return data.get("data", [])
        except httpx.RequestError as exc:
            logger.error("Nango connection error fetching integrations: %s", exc)
            raise NangoServiceError(f"Network error connecting to Nango API: {exc}")

    def create_connect_session(
        self,
        end_user_id: str,
        email: Optional[str] = None,
        allowed_integrations: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a Connect Session for user authentication modal/redirect:
        POST https://api.nango.dev/connect/sessions
        Returns token, connect_link, and expires_at.
        """
        url = f"{self.base_url}/connect/sessions"
        end_user: Dict[str, Any] = {"id": end_user_id}
        if email:
            end_user["email"] = email

        payload: Dict[str, Any] = {"end_user": end_user}
        if allowed_integrations:
            payload["allowed_integrations"] = allowed_integrations
        else:
            payload["allowed_integrations"] = [self.slack_integration_id]

        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(url, headers=self._headers(), json=payload)
                if res.status_code not in (200, 201):
                    raise NangoServiceError(f"Failed to create Nango connect session: HTTP {res.status_code} - {res.text}")
                resp_json = res.json()
                return resp_json.get("data", resp_json)
        except httpx.RequestError as exc:
            logger.error("Nango error creating connect session: %s", exc)
            raise NangoServiceError(f"Network error creating Nango connect session: {exc}")

    def list_connections(self) -> List[Dict[str, Any]]:
        """List active connections stored in Nango."""
        url = f"{self.base_url}/connections"
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=self._headers())
                if res.status_code != 200:
                    raise NangoServiceError(f"Failed to list Nango connections: HTTP {res.status_code} - {res.text}")
                data = res.json()
                return data.get("connections", data.get("data", []))
        except httpx.RequestError as exc:
            logger.error("Nango error listing connections: %s", exc)
            raise NangoServiceError(f"Network error listing Nango connections: {exc}")

    def get_connection(self, connection_id: str, provider_config_key: str = "slack") -> Dict[str, Any]:
        """
        Retrieve a connection and its decrypted credentials from Nango.
        GET https://api.nango.dev/connections/{connection_id}?provider_config_key={provider_config_key}
        """
        url = f"{self.base_url}/connections/{connection_id}"
        params = {"provider_config_key": provider_config_key}
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.get(url, headers=self._headers(), params=params)
                if res.status_code != 200:
                    raise NangoServiceError(f"Failed to fetch connection '{connection_id}': HTTP {res.status_code} - {res.text}")
                return res.json()
        except httpx.RequestError as exc:
            logger.error("Nango error fetching connection '%s': %s", connection_id, exc)
            raise NangoServiceError(f"Network error fetching connection: {exc}")

    def delete_connection(self, connection_id: str, provider_config_key: str = "slack") -> bool:
        """
        Delete/disconnect a connection in Nango.
        DELETE https://api.nango.dev/connection/{connection_id}?provider_config_key={provider_config_key}
        """
        url = f"{self.base_url}/connection/{connection_id}"
        params = {"provider_config_key": provider_config_key}
        try:
            with httpx.Client(timeout=10.0) as client:
                res = client.delete(url, headers=self._headers(), params=params)
                return res.status_code in (200, 204)
        except httpx.RequestError as exc:
            logger.error("Nango error deleting connection '%s': %s", connection_id, exc)
            return False

    def create_agent_session(
        self,
        end_user_id: str,
        toolset: str = "*",
        enable_create_connection: bool = True,
    ) -> Dict[str, Any]:
        """
        Create a Nango Agent Session with a remote MCP server URL and session token.
        Follows Nango Quickstart: https://nango.dev/docs/getting-started/quickstart.md
        POST https://api.nango.dev/sessions
        """
        url = f"{self.base_url}/sessions"
        payload: Dict[str, Any] = {
            "tenant": {
                "connections": {
                    "any": [{"tags": {"end_user_id": end_user_id}}]
                }
            },
            "toolset": toolset,
            "meta_tools": {
                "nango_create_connection": {
                    "enabled": enable_create_connection,
                    "tags": {"end_user_id": end_user_id}
                }
            }
        }
        try:
            with httpx.Client(timeout=15.0) as client:
                res = client.post(url, headers=self._headers(), json=payload)
                if res.status_code not in (200, 201):
                    raise NangoServiceError(f"Failed to create Nango agent session: HTTP {res.status_code} - {res.text}")
                resp_json = res.json()
                return resp_json.get("data", resp_json)
        except httpx.RequestError as exc:
            logger.error("Nango error creating agent session: %s", exc)
            raise NangoServiceError(f"Network error creating Nango agent session: {exc}")


# Global singleton instance
nango_service = NangoService()
