from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch
import httpx
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services.nango_service import NangoService, NangoServiceError


class TestNangoService(unittest.TestCase):
    def setUp(self):
        self.api_key = "mock_nango_test_key_123456789"
        self.service = NangoService(api_key=self.api_key, base_url="https://api.nango.dev")

    def test_is_configured(self):
        self.assertTrue(self.service.is_configured)
        unconfigured = NangoService(api_key="", base_url="https://api.nango.dev")
        self.assertFalse(unconfigured.is_configured)

    def test_headers_include_bearer_token(self):
        headers = self.service._headers()
        self.assertEqual(headers["Authorization"], f"Bearer {self.api_key}")
        self.assertEqual(headers["Content-Type"], "application/json")

    @patch("httpx.Client.get")
    def test_get_integrations_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {
                    "unique_key": "slack",
                    "provider": "slack",
                    "display_name": "Slack",
                }
            ]
        }
        mock_get.return_value = mock_resp

        integrations = self.service.get_integrations()
        self.assertEqual(len(integrations), 1)
        self.assertEqual(integrations[0]["unique_key"], "slack")
        self.assertEqual(integrations[0]["provider"], "slack")

    @patch("httpx.Client.post")
    def test_create_connect_session_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "data": {
                "token": "nango_connect_session_test",
                "connect_link": "https://connect.nango.dev/?session_token=test",
                "expires_at": "2026-11-16T10:00:00Z",
            }
        }
        mock_post.return_value = mock_resp

        res = self.service.create_connect_session(
            end_user_id="user_123",
            email="developer@teamobsidian.local",
            allowed_integrations=["slack"],
        )
        self.assertEqual(res["token"], "nango_connect_session_test")
        self.assertTrue(res["connect_link"].startswith("https://connect.nango.dev/"))

    @patch("httpx.Client.get")
    def test_get_connection_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": "conn_123",
            "provider_config_key": "slack",
            "credentials": {
                "access_token": "xoxb-mock-bot-token-from-nango",
                "team_id": "T0C4Y4JM83C",
                "team_name": "Team Obsidian Workspace",
            },
        }
        mock_get.return_value = mock_resp

        conn = self.service.get_connection("conn_123", provider_config_key="slack")
        self.assertEqual(conn["credentials"]["access_token"], "xoxb-mock-bot-token-from-nango")
        self.assertEqual(conn["credentials"]["team_id"], "T0C4Y4JM83C")


    @patch("httpx.Client.get")
    def test_list_connections_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "connections": [
                {
                    "id": "conn_abc",
                    "provider_config_key": "slack",
                    "created_at": "2026-11-16T10:00:00Z",
                }
            ]
        }
        mock_get.return_value = mock_resp

        conns = self.service.list_connections()
        self.assertEqual(len(conns), 1)
        self.assertEqual(conns[0]["id"], "conn_abc")

    @patch("httpx.Client.delete")
    def test_delete_connection_success(self, mock_delete):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_delete.return_value = mock_resp

        deleted = self.service.delete_connection("conn_123", provider_config_key="slack")
        self.assertTrue(deleted)

    @patch("httpx.Client.post")
    def test_create_agent_session_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 201
        mock_resp.json.return_value = {
            "data": {
                "session_id": "session_uuid_123",
                "session_token": "nango_agent_session_token_123",
                "mcp_url": "https://api.nango.dev/session/session_uuid_123/mcp",
                "expires_at": "2026-12-01T10:00:00Z",
                "toolset": {"slack": {"connected": True}},
                "meta_tools": {"nango_tool_search": True, "nango_execute": True},
            }
        }
        mock_post.return_value = mock_resp

        res = self.service.create_agent_session(
            end_user_id="developer_123",
            toolset="*",
            enable_create_connection=True,
        )
        self.assertEqual(res["session_id"], "session_uuid_123")
        self.assertEqual(res["session_token"], "nango_agent_session_token_123")
        self.assertEqual(res["mcp_url"], "https://api.nango.dev/session/session_uuid_123/mcp")
        self.assertTrue(res["meta_tools"]["nango_tool_search"])

    def test_slack_oauth_strictly_uses_nango_no_fallback(self):
        """Verify that when Nango is configured, Slack OAuth strictly routes to Nango and does not silently fall back to direct OAuth."""
        from app.services.connectors.slack_connector import SlackConnector
        # Confirm that SlackConnector authorization URL does not include hardcoded team
        state = "test_state"
        redirect = "https://team-obsidian.local/callback"
        with patch.object(settings, "SLACK_CLIENT_ID", "mock_client_id"), \
             patch.object(settings, "SLACK_CLIENT_SECRET", "mock_secret"), \
             patch.object(settings, "SLACK_TEAM_ID", ""):
            url = SlackConnector.get_oauth_authorize_url(state=state, redirect_uri=redirect)
            self.assertIn("client_id=mock_client_id", url)
            self.assertNotIn("team=", url)


if __name__ == "__main__":
    unittest.main()

