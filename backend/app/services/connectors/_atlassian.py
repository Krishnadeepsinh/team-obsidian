import base64
import html
import ipaddress
import re
import socket
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode, urlparse

from app.services.connectors.base import BaseConnector, ConnectorError

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - optional fallback if bs4 missing
    BeautifulSoup = None  # type: ignore

ATLASSIAN_AUTH_URL = "https://auth.atlassian.com/authorize"
ATLASSIAN_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_RESOURCES_URL = "https://api.atlassian.com/oauth/token/accessible-resources"
ATLASSIAN_ME_URL = "https://api.atlassian.com/me"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\n{3,}")


def validate_external_https_url(url: str, label: str = "Site URL") -> str:
    """Validate user-supplied external base URL against SSRF to private/loopback addresses."""
    cleaned = (url or "").strip().rstrip("/")
    if not cleaned:
        raise ConnectorError(f"{label} is required.")
    if not cleaned.startswith("https://"):
        raise ConnectorError(f"{label} must start with https://")
    parsed = urlparse(cleaned)
    host = (parsed.hostname or "").strip().lower()
    if not host or host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        raise ConnectorError(f"{label} cannot target a local or private host.")

    # 1. Reject direct private/loopback/reserved IP literals
    try:
        ip = ipaddress.ip_address(host)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise ConnectorError(f"{label} cannot target a private or reserved IP address.")
    except ValueError:
        pass

    # 2. Resolve hostname using socket.getaddrinfo() and reject any private/loopback/reserved IPv4/IPv6
    try:
        addr_infos = socket.getaddrinfo(host, None)
        if not addr_infos:
            raise ConnectorError(f"{label} host could not be resolved.")
        for info in addr_infos:
            sockaddr = info[4]
            ip_str = sockaddr[0]
            try:
                resolved_ip = ipaddress.ip_address(ip_str)
                # RFC 6052 Well-Known Prefix 64:ff9b::/96 translates an IPv4 address to IPv6
                if resolved_ip.version == 6 and resolved_ip in ipaddress.ip_network("64:ff9b::/96"):
                    resolved_ip = ipaddress.ip_address(resolved_ip.packed[-4:])
                if (
                    resolved_ip.is_private
                    or resolved_ip.is_loopback
                    or resolved_ip.is_link_local
                    or resolved_ip.is_reserved
                    or resolved_ip.is_multicast
                    or resolved_ip.is_unspecified
                ):
                    raise ConnectorError(f"{label} resolves to a private or reserved IP address ({ip_str}).")
            except ValueError:
                raise ConnectorError(f"{label} returned an invalid IP address ({ip_str}).")
    except socket.gaierror as exc:
        raise ConnectorError(f"{label} host could not be resolved: {exc}")

    return f"https://{parsed.netloc}{parsed.path}".rstrip("/")


def html_to_clean_text(raw_html: str) -> str:
    """Convert Confluence XHTML storage format or rich HTML into clean readable plain text."""
    if not raw_html:
        return ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text("\n")
    else:
        text = _TAG_RE.sub("\n", raw_html)
    lines = [line.strip() for line in html.unescape(text).splitlines()]
    compact = "\n".join(line for line in lines if line)
    return _WS_RE.sub("\n\n", compact).strip()


def flatten_adf(node: Any) -> str:
    """Flatten Atlassian Document Format (ADF) JSON nodes recursively into readable text."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (flatten_adf(item) for item in node) if part)
    if not isinstance(node, dict):
        return str(node)

    ntype = node.get("type")
    if ntype == "text":
        return str(node.get("text") or "")
    if ntype == "hardBreak":
        return "\n"
    if ntype == "mention":
        attrs = node.get("attrs") or {}
        return str(attrs.get("text") or attrs.get("id") or "")

    children = node.get("content") or []
    parts = [flatten_adf(child) for child in children]
    joined = ("" if ntype == "paragraph" else "\n").join(p for p in parts if p)
    if ntype in {"heading", "paragraph", "bulletList", "orderedList", "listItem", "blockquote", "codeBlock"}:
        return joined.strip()
    return joined


def parse_atlassian_auth(
    token: Optional[str],
    email: Optional[str] = None,
    site_url: Optional[str] = None,
    cloud_id: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    """Normalize either Atlassian OAuth 3LO Bearer token or 'site_url|email|api_token' Basic credentials."""
    raw = (token or "").strip()
    resolved_email = (email or "").strip() or None
    resolved_site = (site_url or "").strip().rstrip("/") or None
    resolved_cloud = (cloud_id or "").strip() or None
    secret_token = raw

    if "|" in raw:
        parts = [p.strip() for p in raw.split("|", 2)]
        if len(parts) == 3 and parts[0] and parts[1] and parts[2]:
            resolved_site, resolved_email, secret_token = parts[0].rstrip("/"), parts[1], parts[2]
        elif len(parts) == 2 and "@" in parts[0]:
            resolved_email, secret_token = parts[0], parts[1]
    elif ":" in raw and "@" in raw.split(":", 1)[0] and not resolved_email:
        maybe_email, maybe_tok = raw.split(":", 1)
        resolved_email, secret_token = maybe_email.strip(), maybe_tok.strip()

    if resolved_site:
        resolved_site = validate_external_https_url(resolved_site, "Atlassian Site URL")

    return {
        "token": secret_token or None,
        "email": resolved_email,
        "site_url": resolved_site,
        "cloud_id": resolved_cloud,
    }


def build_atlassian_headers(parsed: Dict[str, Optional[str]]) -> Tuple[Dict[str, str], str]:
    """Build Authorization + Accept headers and detect auth mode ('basic' or 'oauth')."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "Team-Obsidian-Platform/2.0",
    }
    tok = parsed.get("token")
    email = parsed.get("email")
    if tok and email:
        basic = base64.b64encode(f"{email}:{tok}".encode("utf-8")).decode("utf-8")
        headers["Authorization"] = f"Basic {basic}"
        return headers, "basic"
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return headers, "oauth"


def fetch_accessible_resources(connector: BaseConnector, headers: Dict[str, str]) -> List[Dict[str, Any]]:
    """Query Atlassian accessible cloud resources for an OAuth 3LO Bearer token."""
    res = connector._request_with_retry("GET", ATLASSIAN_RESOURCES_URL, headers=headers, timeout=10)
    if res.status_code != 200:
        raise ConnectorError(f"Atlassian accessible-resources lookup failed ({res.status_code}): {res.text[:200]}")
    data = res.json() if res.text else []
    return data if isinstance(data, list) else []


def pick_atlassian_resource(
    resources: List[Dict[str, Any]], scope_keyword: str
) -> Optional[Dict[str, Any]]:
    """Select best Atlassian Cloud site matching Jira or Confluence scopes."""
    if not resources:
        return None
    for site in resources:
        scopes = [str(s).lower() for s in (site.get("scopes") or [])]
        if any(scope_keyword in s for s in scopes):
            return site
    return resources[0]


def atlassian_authorize_url(
    client_id: str,
    client_secret: str,
    scopes: str,
    state: str,
    redirect_uri: str,
    provider_label: str,
) -> str:
    if not client_id or not client_secret:
        raise ConnectorError(
            f"{provider_label} OAuth is not configured. Set ATLASSIAN_CLIENT_ID and ATLASSIAN_CLIENT_SECRET in backend .env."
        )
    params = urlencode({
        "audience": "api.atlassian.com",
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": state,
        "response_type": "code",
        "prompt": "consent",
    })
    return f"{ATLASSIAN_AUTH_URL}?{params}"


def atlassian_exchange_oauth_code(
    connector: BaseConnector,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    scope_keyword: str,
) -> Dict[str, Any]:
    if not client_id or not client_secret:
        raise ConnectorError("Missing ATLASSIAN_CLIENT_ID or ATLASSIAN_CLIENT_SECRET.")
    res = connector._request_with_retry(
        "POST",
        ATLASSIAN_TOKEN_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json_body={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        timeout=12,
    )
    payload = res.json() if res.text else {}
    access_token = payload.get("access_token")
    if res.status_code != 200 or not access_token:
        raise ConnectorError(
            f"Atlassian OAuth exchange failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
        )

    bundle: Dict[str, Any] = {
        "access_token": access_token,
        "token": access_token,
        "scope": payload.get("scope", ""),
        "token_type": payload.get("token_type", "Bearer"),
        **({"refresh_token": payload["refresh_token"]} if payload.get("refresh_token") else {}),
        **({"expires_in": payload["expires_in"]} if payload.get("expires_in") else {}),
    }
    try:
        sites = fetch_accessible_resources(connector, {"Authorization": f"Bearer {access_token}", "Accept": "application/json"})
        site = pick_atlassian_resource(sites, scope_keyword)
        if site:
            bundle["cloud_id"] = site.get("id")
            bundle["site_url"] = (site.get("url") or "").rstrip("/")
            bundle["site_name"] = site.get("name")
    except ConnectorError:
        pass
    return bundle


def atlassian_refresh_oauth_token(
    connector: BaseConnector,
    client_id: str,
    client_secret: str,
    refresh_token: str,
) -> Dict[str, Any]:
    if not client_id or not client_secret:
        raise ConnectorError("Missing ATLASSIAN_CLIENT_ID or ATLASSIAN_CLIENT_SECRET.")
    res = connector._request_with_retry(
        "POST",
        ATLASSIAN_TOKEN_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json_body={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=12,
    )
    payload = res.json() if res.text else {}
    access_token = payload.get("access_token")
    if res.status_code != 200 or not access_token:
        raise ConnectorError(
            f"Atlassian token refresh failed: {payload.get('error_description') or payload.get('error') or res.status_code}"
        )
    return {
        "access_token": access_token,
        "token": access_token,
        "scope": payload.get("scope", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "refresh_token": payload.get("refresh_token") or refresh_token,
        **({"expires_in": payload["expires_in"]} if payload.get("expires_in") else {}),
    }

