import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

from app.core.config import settings
from app.services.connectors.base import BaseConnector, ConnectorError, compute_sha256


class SlackConnector(BaseConnector):
    """Slack connector supporting OAuth v2, Bot Token verification, channel listing, pagination, and full thread replies."""

    provider_name = "slack"

    def __init__(self, token: Optional[str] = None):
        super().__init__(token=token)
        self.base_url = "https://slack.com/api"
        self.headers = {"Content-Type": "application/json"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"
        self._user_cache: Dict[str, str] = {}

    @classmethod
    def get_oauth_authorize_url(cls, state: str, redirect_uri: str) -> str:
        if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
            raise ConnectorError(
                "Slack OAuth App is not configured. Set SLACK_CLIENT_ID and SLACK_CLIENT_SECRET in backend .env."
            )
        params = urlencode({
            "client_id": settings.SLACK_CLIENT_ID,
            "scope": "channels:read,channels:history,groups:read,groups:history,users:read,team:read",
            "redirect_uri": redirect_uri,
            "state": state,
        })
        return f"https://slack.com/oauth/v2/authorize?{params}"

    @classmethod
    def exchange_oauth_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        if not settings.SLACK_CLIENT_ID or not settings.SLACK_CLIENT_SECRET:
            raise ConnectorError("Missing SLACK_CLIENT_ID or SLACK_CLIENT_SECRET.")
        connector = cls()
        res = connector._request_with_retry(
            "POST",
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": settings.SLACK_CLIENT_ID,
                "client_secret": settings.SLACK_CLIENT_SECRET,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        payload = res.json() if res.text else {}
        if not payload.get("ok") or not payload.get("access_token"):
            raise ConnectorError(f"Slack OAuth failed: {payload.get('error', res.status_code)}")
        return {
            "access_token": payload["access_token"],
            "token": payload["access_token"],
            "bot_token": payload["access_token"],
            "scope": payload.get("scope", ""),
            "team_name": (payload.get("team") or {}).get("name"),
            "team_id": (payload.get("team") or {}).get("id"),
        }

    def check_connection(self) -> Dict[str, Any]:
        if not self.token:
            return {
                "status": "unconfigured",
                "auth_type": "none",
                "message": "Missing Slack Bot OAuth token.",
            }
        try:
            res = self._request_with_retry("POST", f"{self.base_url}/auth.test", headers=self.headers, timeout=8)
            data = res.json()
            if data.get("ok"):
                raw_scopes = res.headers.get("X-OAuth-Scopes", "")
                scopes = [s.strip() for s in raw_scopes.split(",") if s.strip()]
                return {
                    "status": "connected",
                    "auth_type": "bot_token",
                    "team": data.get("team"),
                    "team_id": data.get("team_id"),
                    "user": data.get("user"),
                    "connected_account": f"{data.get('team', 'Slack')} (@{data.get('user', 'bot')})",
                    "scopes": scopes,
                }
            return {"status": "error", "message": data.get("error", "Slack authentication failed")}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def _resolve_user(self, user_id: str) -> str:
        if not user_id:
            return "slack_user"
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        try:
            res = self._request_with_retry(
                "GET",
                f"{self.base_url}/users.info",
                headers=self.headers,
                params={"user": user_id},
            )
            data = res.json()
            if data.get("ok"):
                u = data.get("user") or {}
                profile = u.get("profile") or {}
                name = profile.get("display_name") or profile.get("real_name") or u.get("name") or user_id
                self._user_cache[user_id] = name
                return name
        except Exception:
            pass
        self._user_cache[user_id] = user_id
        return user_id

    def list_channels(self) -> List[Dict[str, Any]]:
        if not self.token:
            return []
        channels: List[Dict[str, Any]] = []
        cursor = None
        for page_idx in range(5):
            params: Dict[str, Any] = {"types": "public_channel,private_channel", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            res = self._request_with_retry("GET", f"{self.base_url}/conversations.list", headers=self.headers, params=params)
            if res.status_code != 200:
                if page_idx == 0:
                    raise ConnectorError(f"Slack rejected channel lookup ({res.status_code}): {res.text[:200]}")
                break
            data = res.json()
            if not data.get("ok"):
                if page_idx == 0:
                    raise ConnectorError(f"Slack failed to list channels: {data.get('error', 'unknown_error')}")
                break
            for ch in data.get("channels", []):
                channels.append({"id": ch.get("id"), "name": ch.get("name"), "is_member": ch.get("is_member", False)})
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
        return channels

    def sync_channel_messages(
        self,
        channel_id: str,
        channel_name: Optional[str] = None,
        oldest_ts: Optional[str] = None,
        max_pages: int = 10,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Fetch paginated Slack conversation history and full thread replies."""
        if not self.token:
            raise ConnectorError("Missing Slack Bot OAuth token.")

        raw_channel = (channel_id or "").strip().lstrip("#")
        if raw_channel and not re.match(r"^[CDG][A-Z0-9]{6,}$", raw_channel):
            channels = self.list_channels()
            match = next(
                (c for c in channels if c.get("name") == raw_channel or c.get("id") == raw_channel),
                None,
            )
            if not match or not match.get("id"):
                raise ConnectorError(f"Slack channel '{channel_id}' not found or inaccessible to the bot.")
            channel_id = match["id"]
            channel_name = channel_name or match.get("name")
        else:
            channel_id = raw_channel

        records: List[Dict[str, Any]] = []
        cursor: Optional[str] = None
        newest_ts: Optional[str] = oldest_ts
        label = channel_name or channel_id

        for _ in range(max_pages):
            params: Dict[str, Any] = {"channel": channel_id, "limit": 100}
            if oldest_ts:
                params["oldest"] = oldest_ts
            if cursor:
                params["cursor"] = cursor

            res = self._request_with_retry(
                "GET", f"{self.base_url}/conversations.history", headers=self.headers, params=params
            )
            data = res.json()
            if not data.get("ok"):
                raise ConnectorError(f"Slack history error on channel '{label}': {data.get('error', 'unknown')}")

            messages = data.get("messages", [])
            for msg in messages:
                ts = msg.get("ts", "")
                if not ts:
                    continue
                if not newest_ts or float(ts) > float(newest_ts):
                    newest_ts = ts

                text = (msg.get("text") or "").strip()
                if not text and not msg.get("reply_count"):
                    continue

                author_id = msg.get("user") or msg.get("bot_id") or "slack_user"
                author_name = self._resolve_user(author_id) if msg.get("user") else author_id
                msg_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)

                thread_lines: List[str] = []
                reply_count = int(msg.get("reply_count") or 0)
                if reply_count > 0:
                    try:
                        rep_res = self._request_with_retry(
                            "GET",
                            f"{self.base_url}/conversations.replies",
                            headers=self.headers,
                            params={"channel": channel_id, "ts": ts, "limit": 100},
                        )
                        rep_data = rep_res.json()
                        if rep_data.get("ok"):
                            for rep in rep_data.get("messages", [])[1:]:
                                r_author = self._resolve_user(rep.get("user") or "member")
                                r_text = (rep.get("text") or "").strip()
                                if r_text:
                                    thread_lines.append(f"  - {r_author}: {r_text}")
                    except Exception:
                        pass

                content = f"Slack Thread in #{label} ({msg_dt.isoformat()})\nStarted by {author_name}:\n{text}"
                if thread_lines:
                    content += "\n\nThread Replies:\n" + "\n".join(thread_lines)

                source_type = "slack_thread" if thread_lines else "slack_message"
                records.append({
                    "source_type": source_type,
                    "external_id": f"{channel_id}-{ts}",
                    "title": f"Slack #{label}: {text[:70]}" + ("..." if len(text) > 70 else ""),
                    "author": author_name,
                    "url": f"https://slack.com/archives/{channel_id}/p{ts.replace('.', '')}",
                    "content": content,
                    "sha256": compute_sha256(content),
                    "source_timestamp": msg_dt,
                    "metadata": {
                        "channel_id": channel_id,
                        "channel_name": label,
                        "reply_count": len(thread_lines),
                        "ts": ts,
                    },
                    "raw_payload": msg,
                })

            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break

        return records, newest_ts

    def sync(
        self,
        config: Optional[Dict[str, Any]] = None,
        sync_cursor: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = config or {}
        cursor = dict(sync_cursor or {})

        target_channels: List[Dict[str, str]] = []
        raw_channels = cfg.get("channels")
        tokens: List[str] = []
        if isinstance(raw_channels, list) and raw_channels:
            tokens = [str(t).strip().lstrip("#") for t in raw_channels if str(t).strip()]
        else:
            raw_target = str(cfg.get("channel_id") or cfg.get("channel") or cfg.get("target") or "").strip()
            if raw_target:
                tokens = [t.strip().lstrip("#") for t in raw_target.split(",") if t.strip()]

        channels_list = self.list_channels()

        if tokens:
            for tok in tokens:
                matched = [c for c in channels_list if c.get("id") == tok or c.get("name") == tok]
                target_channels.extend(matched or [{"id": tok, "name": tok}])
        else:
            target_channels = [c for c in channels_list if c.get("is_member")][:10]
            if not target_channels and channels_list:
                raise ConnectorError(
                    "Slack app is connected, but @Team Obsidian has not been invited to any channel yet. "
                    "In Slack, run /invite @Team Obsidian in the channels you want to sync (or specify a Channel ID)."
                )

        if not target_channels:
            raise ConnectorError("No accessible Slack channels found. Invite the bot to channels first.")

        all_records: List[Dict[str, Any]] = []
        for ch in target_channels:
            ch_id = ch["id"]
            oldest_ts = cursor.get(ch_id)
            recs, newest_ts = self.sync_channel_messages(ch_id, channel_name=ch.get("name"), oldest_ts=oldest_ts)
            all_records.extend(recs)
            if newest_ts:
                cursor[ch_id] = newest_ts

        return all_records, cursor


slack_connector = SlackConnector()
