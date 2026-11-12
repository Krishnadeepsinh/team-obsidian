import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
import httpx
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
from app.core.pipeline_tracker import pipeline_tracker
from app.core.security import (
    create_oauth_state_token,
    decode_access_token,
    decrypt_credentials,
    encrypt_credentials,
    get_current_user,
    mask_credentials,
)
from app.models.integration import Integration, SourceEvent, SourceRecord
from app.models.workspace import User
from app.schemas.integration import (
    IntegrationCreate,
    IntegrationResponse,
    SourceEventResponse,
    SyncResultResponse,
)
from app.services.audit_service import record_activity
from app.services.connectors import (
    ConfluenceConnector,
    ConnectorError,
    GitHubConnector,
    GitLabConnector,
    JiraConnector,
    LinearConnector,
    NotionConnector,
    SentryConnector,
    SlackConnector,
    get_connector_class,
)
from app.services.ingestion_service import upsert_source_records
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

logger = logging.getLogger("team_obsidian.integrations")
router = APIRouter(prefix="/integrations", tags=["Source Connections"])


class ReconnectRequest(BaseModel):
    credentials: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]
    name: Optional[str] = None


class DiscoverResourcesRequest(BaseModel):
    provider: str
    token: Optional[str] = None
    credentials: Optional[Dict[str, Any]] = None


def _to_response(i: Integration) -> IntegrationResponse:
    return IntegrationResponse(
        id=i.id,
        project_id=i.project_id,
        provider=i.provider,
        name=i.name,
        status=i.status,
        auth_type=i.auth_type,
        auth_status=getattr(i, "auth_status", "unverified") or "unverified",
        connected_account=getattr(i, "connected_account", None),
        scopes=getattr(i, "scopes", None) or [],
        credentials=mask_credentials(i.credentials),
        config=i.config or {},
        last_sync=i.last_sync,
        error_message=i.error_message,
        items_synced=i.items_synced,
        created_at=i.created_at,
        updated_at=i.updated_at,
    )


def _token_from_dict(creds: Optional[Dict[str, Any]]) -> Optional[str]:
    if not creds:
        return None
    return creds.get("access_token") or creds.get("token") or creds.get("api_key") or creds.get("bot_token")


def _build_connector(connector_cls: Any, token: Optional[str], creds: Optional[Dict[str, Any]] = None) -> Any:
    """Instantiate a connector passing optional provider-specific credential fields when supported."""
    c = creds or {}
    if connector_cls in (JiraConnector, ConfluenceConnector):
        return connector_cls(
            token=token,
            email=c.get("email"),
            site_url=c.get("site_url"),
            cloud_id=c.get("cloud_id"),
        )
    if connector_cls is GitLabConnector:
        return connector_cls(token=token, site_url=c.get("site_url"))
    if connector_cls is SentryConnector:
        return connector_cls(token=token, org_slug=c.get("org_slug"), site_url=c.get("site_url"))
    return connector_cls(token=token)


def _extract_token(integ: Integration) -> Optional[str]:
    """Extract only the credentials bound to this integration (never fall back to host env tokens)."""
    return _token_from_dict(decrypt_credentials(integ.credentials))


def _refresh_oauth_token_if_possible(db: Session, integ: Integration) -> Optional[str]:
    connector_cls = get_connector_class(integ.provider)
    if not connector_cls or not hasattr(connector_cls, "refresh_oauth_token"):
        return None
    creds = decrypt_credentials(integ.credentials)
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return None
    try:
        new_bundle = connector_cls.refresh_oauth_token(refresh_token)
        # Preserve cached Atlassian cloud_id/site_url/email or Sentry org metadata across token refreshes
        merged = {**creds, **new_bundle}
        integ.credentials = encrypt_credentials(merged)
        integ.error_message = None
        db.commit()
        db.refresh(integ)
        return merged.get("access_token") or merged.get("token")
    except ConnectorError:
        return None


def _refresh_github_token_if_possible(db: Session, integ: Integration) -> Optional[str]:
    if (integ.provider or "").lower() != "github":
        return None
    return _refresh_oauth_token_if_possible(db, integ)


def _discover_provider_resources(
    provider: str, token: str, creds: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    prov = (provider or "").lower().strip()
    if prov == "github":
        repos = GitHubConnector(token=token).list_repositories(max_pages=3)
        resources = [
            {
                "id": r.get("full_name"),
                "label": r.get("full_name"),
                "sublabel": f"{'Private' if r.get('private') else 'Public'} • branch: {r.get('default_branch') or 'main'}",
                "value": r.get("full_name"),
                "url": r.get("html_url"),
                "private": bool(r.get("private", False)),
                "default_branch": r.get("default_branch") or "main",
            }
            for r in repos
            if r.get("full_name")
        ]
        hint = (
            None
            if resources
            else "No repositories were returned for this token. If using a GitHub App OAuth login, ensure the GitHub App is installed on at least one repository under GitHub Settings -> Applications; if using a Personal Access Token, ensure the 'repo' scope is enabled."
        )
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "slack":
        channels = SlackConnector(token=token).list_channels()
        channels_sorted = sorted(channels, key=lambda c: (not bool(c.get("is_member")), (c.get("name") or "").lower()))
        resources = [
            {
                "id": ch.get("id"),
                "label": f"#{ch.get('name') or ch.get('id')}",
                "sublabel": "Bot is a member (ready to sync)" if ch.get("is_member") else "Invite bot with /invite @Team Obsidian in Slack",
                "value": ch.get("id"),
                "name": ch.get("name"),
                "is_member": bool(ch.get("is_member", False)),
            }
            for ch in channels_sorted
            if ch.get("id")
        ]
        hint = (
            None
            if resources
            else "No accessible Slack channels found. Verify channels:read and groups:read scopes on your Slack app."
        )
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "notion":
        items = NotionConnector(token=token).list_accessible_resources(max_pages=2)
        resources = [
            {
                "id": it.get("id"),
                "label": it.get("title") or "Untitled",
                "sublabel": str(it.get("object") or "page").title(),
                "value": it.get("id"),
                "object": it.get("object") or "page",
                "url": it.get("url"),
            }
            for it in items
            if it.get("id")
        ]
        hint = (
            None
            if resources
            else "No Notion pages or databases are shared with this integration yet. Open a Notion page -> '...' -> Connections -> add Team Obsidian."
        )
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "jira":
        conn = _build_connector(JiraConnector, token, creds)
        projects = conn.list_projects()
        resources = [
            {
                "id": p.get("key"),
                "label": f"[{p.get('key')}] {p.get('name') or p.get('key')}",
                "sublabel": f"{str(p.get('project_type') or 'software').title()} Jira project",
                "value": p.get("key"),
                "url": p.get("url"),
            }
            for p in projects
            if p.get("key")
        ]
        hint = None if resources else "No accessible Jira projects found. Verify Jira API scopes or project permissions."
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "confluence":
        conn = _build_connector(ConfluenceConnector, token, creds)
        spaces = conn.list_spaces()
        resources = [
            {
                "id": sp.get("id"),
                "label": f"{sp.get('name') or sp.get('key')} ({sp.get('key')})",
                "sublabel": f"{str(sp.get('type') or 'global').title()} space",
                "value": sp.get("id"),
                "url": sp.get("url"),
            }
            for sp in spaces
            if sp.get("id")
        ]
        hint = None if resources else "No accessible Confluence spaces found. Verify Confluence read scopes."
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "linear":
        teams = LinearConnector(token=token).list_teams()
        resources = [
            {
                "id": t.get("key"),
                "label": f"{t.get('key')} — {t.get('name')}",
                "sublabel": (t.get("description") or "Linear Engineering Team")[:90],
                "value": t.get("key"),
            }
            for t in teams
            if t.get("key")
        ]
        hint = None if resources else "No Linear teams found for this token."
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "gitlab":
        conn = _build_connector(GitLabConnector, token, creds)
        projects = conn.list_projects(max_pages=2)
        resources = [
            {
                "id": p.get("path_with_namespace"),
                "label": p.get("path_with_namespace"),
                "sublabel": f"{str(p.get('visibility') or 'private').title()} • branch: {p.get('default_branch') or 'main'}",
                "value": p.get("path_with_namespace"),
                "url": p.get("web_url"),
            }
            for p in projects
            if p.get("path_with_namespace")
        ]
        hint = None if resources else "No accessible GitLab projects found. Check read_api/read_repository scopes."
        return {"provider": prov, "resources": resources, "hint": hint}

    if prov == "sentry":
        conn = _build_connector(SentryConnector, token, creds)
        projects = conn.list_projects()
        resources = [
            {
                "id": p.get("full_slug"),
                "label": p.get("full_slug"),
                "sublabel": f"Platform: {p.get('platform') or 'app'}",
                "value": p.get("full_slug"),
            }
            for p in projects
            if p.get("full_slug")
        ]
        hint = None if resources else "No Sentry projects found. Verify org:read & project:read scopes on your Auth Token."
        return {"provider": prov, "resources": resources, "hint": hint}

    return {
        "provider": prov,
        "resources": [],
        "hint": f"Resource discovery is not needed for provider '{prov}'.",
    }


def _run_background_sync_extraction(
    project_id: str,
    actor_user_id: str,
    integration_id: Optional[str] = None,
) -> None:
    """Run knowledge extraction asynchronously in an isolated session after integration sync."""
    pipeline_tracker.update(
        project_id,
        stage="extracting_knowledge",
        message="Extracting architectural entities, decisions, and risks from synced sources...",
        progress=70,
        active=True,
        job_type="integration_sync_extraction",
        integration_id=integration_id,
    )
    bg_db = SessionLocal()
    try:
        summary = extract_and_persist_project_knowledge(bg_db, project_id, actor_user_id=actor_user_id)
        pipeline_tracker.update(
            project_id,
            stage="completed",
            message="Integration sync and Knowledge Graph extraction finished.",
            progress=100,
            active=False,
            job_type="integration_sync_extraction",
            integration_id=integration_id,
            details=summary or {},
        )
    except Exception as exc:
        logger.warning("Background sync knowledge extraction skipped for project %s: %s", project_id, exc)
        pipeline_tracker.update(
            project_id,
            stage="failed",
            message=f"Sync completed, but knowledge extraction encountered an issue: {str(exc)[:120]}",
            progress=100,
            active=False,
            job_type="integration_sync_extraction",
            integration_id=integration_id,
            error_message=str(exc)[:500],
        )
        try:
            bg_db.rollback()
        except Exception:
            pass
    finally:
        bg_db.close()


_SAFE_HOST_RE = re.compile(r"^[A-Za-z0-9.-]+(?::\d{1,5})?$")


def _is_trusted_forwarded_host(host: str) -> bool:
    if not host or ".." in host or not _SAFE_HOST_RE.fullmatch(host):
        return False
    hostname = host.split(":")[0].lower()
    if hostname in {"localhost", "127.0.0.1", "testserver"} or hostname.endswith(".onrender.com"):
        return True
    for origin in [settings.BACKEND_URL, *(settings.CORS_ORIGINS or [])]:
        try:
            netloc = urlparse((origin or "").strip()).hostname
            if netloc and hostname == netloc.lower():
                return True
        except Exception:
            continue
    return False


def _resolve_backend_base_url(request: Request) -> str:
    """Resolve external backend base URL cleanly in local dev and reverse-proxied cloud environments."""
    configured = (settings.BACKEND_URL or "").strip().rstrip("/")
    if configured and not configured.startswith("http://localhost") and not configured.startswith("http://127.0.0.1"):
        return configured

    raw_host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    forwarded_host = raw_host.split(",")[0].strip()
    if _is_trusted_forwarded_host(forwarded_host):
        raw_proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        proto = raw_proto.split(",")[0].strip().lower()
        if proto not in {"http", "https"}:
            proto = request.url.scheme if request.url.scheme in {"http", "https"} else "https"
        hostname = forwarded_host.split(":")[0].lower()
        if hostname not in {"localhost", "127.0.0.1", "testserver"}:
            return f"{proto}://{forwarded_host}".rstrip("/")

    return configured or str(request.base_url).rstrip("/")


@router.get("/oauth/{provider}/authorize")
def start_oauth_flow(
    provider: str,
    request: Request,
    project_id: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Generate an authenticated provider OAuth authorization URL."""
    verify_project_access(project_id, current_user, db, require_write=True)
    connector_cls = get_connector_class(provider)
    if not connector_cls:
        raise HTTPException(status_code=400, detail=f"Unsupported OAuth provider '{provider}'.")

    base_url = _resolve_backend_base_url(request)
    redirect_uri = f"{base_url}{settings.API_V1_STR}/integrations/oauth/{provider.lower()}/callback"
    state = create_oauth_state_token({
        "sub": current_user.id,
        "project_id": project_id,
        "provider": provider.lower(),
    })
    try:
        authorize_url = connector_cls.get_oauth_authorize_url(state=state, redirect_uri=redirect_uri)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {"authorize_url": authorize_url, "redirect_uri": redirect_uri, "provider": provider.lower()}


@router.get("/oauth/{provider}/callback")
def oauth_callback(
    provider: str,
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Handle OAuth redirect callback from GitHub, Slack, or Notion."""
    if error:
        return RedirectResponse(f"{settings.FRONTEND_URL}/integrations?oauth_error={quote(str(error), safe='')}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state parameter.")

    payload = decode_access_token(state)
    if not payload or payload.get("token_type") != "oauth_state":
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state token.")
    if (payload.get("provider") or "").lower() != provider.lower():
        raise HTTPException(status_code=400, detail="OAuth state token does not match callback provider.")

    user_id = payload.get("sub")
    project_id = payload.get("project_id")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User for OAuth session no longer exists.")

    verify_project_access(project_id, user, db, require_write=True)
    connector_cls = get_connector_class(provider)
    if not connector_cls:
        raise HTTPException(status_code=400, detail=f"Unsupported OAuth provider '{provider}'.")

    base_url = _resolve_backend_base_url(request)
    redirect_uri = f"{base_url}{settings.API_V1_STR}/integrations/oauth/{provider.lower()}/callback"
    try:
        token_bundle = connector_cls.exchange_oauth_code(code=code, redirect_uri=redirect_uri)
        token = token_bundle.get("access_token") or token_bundle.get("token")
        conn = _build_connector(connector_cls, token=token, creds=token_bundle)
        check = conn.check_connection()
        if check.get("status") != "connected":
            raise ConnectorError(check.get("message", "Provider connection check failed."))
        for k in ("cloud_id", "site_url", "org_slug"):
            if check.get(k) and not token_bundle.get(k):
                token_bundle[k] = check[k]
    except ConnectorError as exc:
        return RedirectResponse(f"{settings.FRONTEND_URL}/integrations?oauth_error={quote(str(exc), safe='')}")

    integ = (
        db.query(Integration)
        .filter(Integration.project_id == project_id, Integration.provider == provider.lower())
        .first()
    )
    if not integ:
        integ = Integration(
            project_id=project_id,
            user_id=user.id,
            provider=provider.lower(),
            name=f"{provider.title()} ({check.get('connected_account') or 'OAuth'})",
        )
        db.add(integ)
        db.flush()

    integ.auth_type = "oauth"
    integ.auth_status = "verified"
    integ.status = "connected"
    integ.connected_account = check.get("connected_account") or token_bundle.get("team_name") or token_bundle.get("workspace_name")
    integ.scopes = check.get("scopes") or []
    integ.credentials = encrypt_credentials(token_bundle)
    integ.error_message = None

    record_activity(
        db=db,
        action="integration.oauth_connected",
        entity_type="integration",
        entity_id=integ.id or provider,
        user_id=user.id,
        project_id=project_id,
        actor_email=user.email,
        details={"message": f"Connected {provider} via OAuth ({integ.connected_account})"},
    )
    db.commit()
    db.refresh(integ)
    return RedirectResponse(
        f"{settings.FRONTEND_URL}/integrations?connected={provider.lower()}&integration_id={integ.id}"
    )


@router.get("", response_model=List[IntegrationResponse])
def list_integrations(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accessible_ids = get_user_accessible_project_ids(current_user, db)
    if project_id:
        verify_project_access(project_id, current_user, db)
        query = db.query(Integration).filter(Integration.project_id == project_id)
    else:
        if not accessible_ids:
            return []
        query = db.query(Integration).filter(Integration.project_id.in_(accessible_ids))

    return [_to_response(i) for i in query.order_by(Integration.created_at.desc()).all()]


@router.get("/jobs")
def list_pipeline_jobs(
    project_id: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List durable background sync & extraction jobs across accessible projects."""
    if project_id:
        verify_project_access(project_id, current_user, db)
        return pipeline_tracker.list_jobs(project_id=project_id, limit=limit)
    accessible_ids = get_user_accessible_project_ids(current_user, db)
    if not accessible_ids:
        return []
    return pipeline_tracker.list_jobs(project_ids=accessible_ids, limit=limit)


@router.get("/{integration_id}/jobs")
def list_integration_jobs(
    integration_id: str,
    limit: int = 20,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List durable sync & extraction jobs for a specific integration."""
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db)
    return pipeline_tracker.list_jobs(project_id=integ.project_id, integration_id=integ.id, limit=limit)


@router.post("", response_model=IntegrationResponse)
def create_integration(
    integ_in: IntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_access(integ_in.project_id, current_user, db, require_write=True)

    provider = (integ_in.provider or "").lower()
    raw_creds = integ_in.credentials or {}
    token = _token_from_dict(raw_creds)

    connected_account = None
    scopes: List[str] = []
    auth_status = "unverified"
    connector_cls = get_connector_class(provider)

    if connector_cls is not None:
        if not token:
            raise HTTPException(
                status_code=400,
                detail=f"Valid authentication credentials are required to connect {provider}.",
            )
        try:
            check = _build_connector(connector_cls, token=token, creds=raw_creds).check_connection()
        except ConnectorError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if check.get("status") != "connected":
            raise HTTPException(
                status_code=400,
                detail=f"{provider.title()} authentication failed: {check.get('message', 'Invalid credentials')}",
            )
        auth_status = "verified"
        connected_account = check.get("connected_account") or check.get("login") or check.get("team") or check.get("bot_name")
        scopes = check.get("scopes") or []
        for k in ("cloud_id", "site_url", "org_slug"):
            if check.get(k) and not raw_creds.get(k):
                raw_creds[k] = check[k]

    integ = Integration(
        project_id=integ_in.project_id,
        user_id=current_user.id,
        is_org_level=bool(integ_in.is_org_level),
        provider=provider,
        name=integ_in.name.strip(),
        auth_type=integ_in.auth_type or "api_token",
        auth_status=auth_status,
        connected_account=connected_account,
        scopes=scopes,
        credentials=encrypt_credentials(raw_creds),
        config=integ_in.config or {},
        status="connected",
        items_synced=0,
    )
    db.add(integ)
    db.flush()

    record_activity(
        db=db,
        action="integration.connected",
        entity_type="integration",
        entity_id=integ.id,
        user_id=current_user.id,
        project_id=integ.project_id,
        actor_email=current_user.email,
        details={"message": f"Connected {integ.provider} integration '{integ.name}'"},
    )
    db.commit()
    db.refresh(integ)
    return _to_response(integ)


@router.post("/discover-resources")
def discover_resources_with_token(
    req: DiscoverResourcesRequest,
    current_user: User = Depends(get_current_user),
):
    """Discover selectable repositories, Slack channels, or Notion pages/databases using a candidate token before saving."""
    token = (req.token or _token_from_dict(req.credentials) or "").strip()
    if not token:
        raise HTTPException(
            status_code=400,
            detail=f"Please enter a valid {req.provider.title()} token first to load available resources.",
        )
    try:
        return _discover_provider_resources(req.provider, token, creds=req.credentials)
    except ConnectorError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{integration_id}/resources")
def list_integration_resources(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List repositories, channels, projects, or spaces accessible to an existing integration."""
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db)

    creds = decrypt_credentials(integ.credentials)
    token = _token_from_dict(creds)
    if not token:
        raise HTTPException(
            status_code=400,
            detail=f"Integration '{integ.name}' has no saved credentials. Please reconnect or enter a token.",
        )
    try:
        return _discover_provider_resources(integ.provider, token, creds=creds)
    except ConnectorError as exc:
        refreshed = _refresh_oauth_token_if_possible(db, integ)
        if refreshed:
            try:
                return _discover_provider_resources(integ.provider, refreshed, creds=decrypt_credentials(integ.credentials))
            except ConnectorError as exc2:
                raise HTTPException(status_code=400, detail=str(exc2))
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{integration_id}/verify")
def verify_integration(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db)

    connector_cls = get_connector_class(integ.provider)
    if not connector_cls:
        return {"status": integ.status, "auth_status": integ.auth_status}

    creds = decrypt_credentials(integ.credentials)
    token = _token_from_dict(creds)
    check = _build_connector(connector_cls, token=token, creds=creds).check_connection()
    if check.get("status") != "connected":
        refreshed = _refresh_oauth_token_if_possible(db, integ)
        if refreshed:
            check = _build_connector(
                connector_cls, token=refreshed, creds=decrypt_credentials(integ.credentials)
            ).check_connection()
    if check.get("status") == "connected":
        integ.auth_status = "verified"
        integ.status = "connected"
        integ.connected_account = check.get("connected_account") or integ.connected_account
        integ.scopes = check.get("scopes") or integ.scopes
        integ.error_message = None
    else:
        integ.auth_status = "error"
        integ.status = "error"
        integ.error_message = check.get("message")
        integ.last_error_at = datetime.now(timezone.utc)
    db.commit()
    return check


@router.get("/{integration_id}/events", response_model=List[SourceEventResponse])
def list_integration_events(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db)
    return (
        db.query(SourceEvent)
        .filter(SourceEvent.integration_id == integration_id)
        .order_by(SourceEvent.timestamp.desc())
        .limit(30)
        .all()
    )


@router.put("/{integration_id}/config", response_model=IntegrationResponse)
def update_integration_config(
    integration_id: str,
    req: ConfigUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)
    next_cfg = dict(req.config or {})
    if "sync_interval_minutes" in next_cfg:
        try:
            cadence = max(0, min(10080, int(next_cfg["sync_interval_minutes"])))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="sync_interval_minutes must be an integer between 0 and 10080.")
        next_cfg["sync_interval_minutes"] = cadence
    integ.config = next_cfg
    if req.name:
        integ.name = req.name.strip()
    db.commit()
    db.refresh(integ)
    return _to_response(integ)


@router.post("/{integration_id}/sync", response_model=SyncResultResponse)
def trigger_sync(
    integration_id: str,
    background_tasks: BackgroundTasks,
    extract_knowledge: bool = Query(True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)

    token = _extract_token(integ)
    provider = (integ.provider or "").lower()
    if not token:
        integ.status = "error"
        integ.auth_status = "error"
        integ.error_message = f"Missing external credentials for '{integ.name}'."
        integ.last_error_at = datetime.now(timezone.utc)
        db.add(
            SourceEvent(
                integration_id=integ.id,
                event_type="sync_failed",
                status="error",
                records_added=0,
                error_message=integ.error_message,
                details={"provider": provider},
            )
        )
        db.commit()
        raise HTTPException(
            status_code=400,
            detail=f"Integration sync BLOCKED: Missing external credentials for '{integ.name}'. Please provide valid API token or complete OAuth.",
        )

    connector_cls = get_connector_class(provider)
    if not connector_cls:
        raise HTTPException(status_code=400, detail=f"Provider '{provider}' does not have an automated sync connector.")

    creds = decrypt_credentials(integ.credentials)
    connector = _build_connector(connector_cls, token=token, creds=creds)
    try:
        synced_records, new_cursor = connector.sync(config=integ.config or {}, sync_cursor=integ.sync_cursor or {})
    except ConnectorError as exc:
        refreshed = _refresh_oauth_token_if_possible(db, integ)
        if refreshed:
            try:
                synced_records, new_cursor = _build_connector(
                    connector_cls, token=refreshed, creds=decrypt_credentials(integ.credentials)
                ).sync(config=integ.config or {}, sync_cursor=integ.sync_cursor or {})
            except ConnectorError as exc2:
                exc = exc2
            else:
                exc = None
        if exc is not None:
            integ.status = "error"
            integ.error_message = str(exc)
            integ.last_error_at = datetime.now(timezone.utc)
            db.add(
                SourceEvent(
                    integration_id=integ.id,
                    event_type="sync_failed",
                    status="error",
                    records_added=0,
                    error_message=str(exc),
                    details={"provider": provider},
                )
            )
            db.commit()
            raise HTTPException(status_code=400, detail=str(exc))

    counts = upsert_source_records(
        db=db,
        integration=integ,
        raw_records=synced_records,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
    )

    # Persist AST graph facts directly when repository AST summary records were indexed
    ast_graph_added = 0
    for rec in synced_records:
        if rec.get("source_type") in ("github_ast", "gitlab_ast"):
            meta = rec.get("metadata") or {}
            repo_name = meta.get("repository") or integ.name
            ast_facts = meta.get("ast_facts") or {}
            if ast_facts:
                try:
                    from app.services.code_ast_indexer import persist_ast_graph_facts

                    ast_graph_added += persist_ast_graph_facts(db, integ.project_id, repo_name, ast_facts)
                except Exception:
                    pass

    integ.sync_cursor = new_cursor
    integ.status = "connected"
    integ.auth_status = "verified"
    integ.error_message = None
    integ.last_sync = datetime.now(timezone.utc)
    db.commit()

    drift_result = {"detected": 0}
    if counts["added"] > 0 or counts["updated"] > 0:
        try:
            from app.services.drift_detector import scan_project_for_drift

            drift_result = scan_project_for_drift(db, integ.project_id, actor_user_id=current_user.id)
        except Exception:
            drift_result = {"detected": 0}

    extracted: Dict[str, Any] = {}
    if extract_knowledge and (counts["added"] > 0 or counts["updated"] > 0):
        pipeline_tracker.update(
            integ.project_id,
            stage="queued",
            message=f"Synced {integ.name} ({counts['added']} new, {counts['updated']} updated). Queued knowledge extraction...",
            progress=40,
            active=True,
            job_type="integration_sync_extraction",
            integration_id=integ.id,
            details={"integration_id": integ.id, "added": counts["added"], "updated": counts["updated"]},
        )
        background_tasks.add_task(_run_background_sync_extraction, integ.project_id, current_user.id, integ.id)
        extracted = {"status": "scheduled", "message": "Knowledge graph extraction scheduled in background."}

    return SyncResultResponse(
        integration_id=integ.id,
        status="success",
        items_processed=len(synced_records),
        records_added=counts["added"],
        records_updated=counts["updated"],
        records_skipped=counts["skipped"],
        details={
            "message": f"Synced {integ.name}: {counts['added']} added, {counts['updated']} updated, {counts['skipped']} deduplicated.",
            "extracted_knowledge": extracted,
            "ast_facts_added": ast_graph_added,
            "drift_detected": drift_result.get("detected", 0),
        },
    )


@router.get("/{integration_id}/webhook-config")
def get_webhook_config(
    integration_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db)
    base_url = _resolve_backend_base_url(request)
    creds = decrypt_credentials(integ.credentials)
    has_secret = bool(creds.get("webhook_secret"))
    return {
        "integration_id": integ.id,
        "provider": integ.provider,
        "webhook_url": f"{base_url}/api/v1/webhooks/{integ.provider}/{integ.id}",
        "has_secret": has_secret,
        "signature_header": {
            "github": "X-Hub-Signature-256",
            "slack": "X-Slack-Signature",
            "notion": "X-Notion-Signature",
            "gitlab": "X-Gitlab-Token",
            "linear": "Linear-Signature",
            "jira": "X-Hub-Signature",
            "sentry": "Sentry-Hook-Signature",
        }.get((integ.provider or "").lower(), "X-Hub-Signature-256"),
    }


@router.post("/{integration_id}/webhook-config")
def generate_webhook_secret(
    integration_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)

    new_secret = secrets.token_urlsafe(32)
    creds = decrypt_credentials(integ.credentials)
    creds["webhook_secret"] = new_secret
    integ.credentials = encrypt_credentials(creds)
    base_url = _resolve_backend_base_url(request)
    webhook_url = f"{base_url}/api/v1/webhooks/{integ.provider}/{integ.id}"

    record_activity(
        db=db,
        action="integration.webhook_secret_rotated",
        entity_type="integration",
        entity_id=integ.id,
        user_id=current_user.id,
        project_id=integ.project_id,
        actor_email=current_user.email,
        details={"message": f"Generated signed webhook endpoint for {integ.name}"},
    )
    db.commit()
    return {
        "integration_id": integ.id,
        "provider": integ.provider,
        "webhook_url": webhook_url,
        "webhook_secret": new_secret,
        "has_secret": True,
        "note": "Store this webhook secret in your provider webhook settings. It will not be shown again in plain text.",
    }


@router.post("/{integration_id}/auto-webhook")
def register_provider_auto_webhook(
    integration_id: str,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Automatically register a signed webhook receiver on configured repositories/apps when supported."""
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)

    creds = decrypt_credentials(integ.credentials)
    access_token = _token_from_dict(creds)
    secret_created = False
    webhook_secret = creds.get("webhook_secret")
    if not webhook_secret:
        webhook_secret = secrets.token_urlsafe(32)
        creds["webhook_secret"] = webhook_secret
        integ.credentials = encrypt_credentials(creds)
        secret_created = True

    base_url = _resolve_backend_base_url(request)
    webhook_url = f"{base_url}/api/v1/webhooks/{integ.provider}/{integ.id}"
    prov = (integ.provider or "").lower()
    cfg = dict(integ.config or {})

    if prov != "github":
        db.commit()
        return {
            "integration_id": integ.id,
            "provider": integ.provider,
            "mode": "manual_setup",
            "webhook_url": webhook_url,
            "webhook_secret": webhook_secret if secret_created else None,
            "has_secret": True,
            "results": [],
            "message": f"{integ.provider.title()} signed webhook URL is ready; add this endpoint in your {integ.provider.title()} app dashboard.",
        }

    # Parse configured GitHub repositories
    raw_repos = cfg.get("repos")
    repos: List[str] = []
    if isinstance(raw_repos, list):
        repos.extend(str(r).strip() for r in raw_repos if str(r).strip())
    single_repo = cfg.get("repo") or cfg.get("target")
    if isinstance(single_repo, str) and single_repo.strip():
        for part in single_repo.split(","):
            p_clean = part.strip()
            if p_clean and p_clean not in repos:
                repos.append(p_clean)

    if not repos:
        db.commit()
        raise HTTPException(
            status_code=400,
            detail="Select at least one GitHub repository in integration configuration before registering webhooks.",
        )
    if not access_token:
        db.commit()
        raise HTTPException(status_code=400, detail="Integration has no active GitHub token. Reconnect first.")

    results: List[Dict[str, Any]] = []
    registered_repos: List[str] = list(cfg.get("auto_webhook_repos") or [])
    with httpx.Client(timeout=12.0) as client_http:
        for repo in repos:
            if "/" not in repo:
                results.append({"repo": repo, "status": "skipped", "detail": "Invalid owner/repo format"})
                continue
            try:
                resp = client_http.post(
                    f"https://api.github.com/repos/{repo}/hooks",
                    headers={
                        "Authorization": f"Bearer {access_token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    json={
                        "name": "web",
                        "active": True,
                        "events": ["push", "pull_request", "issues"],
                        "config": {
                            "url": webhook_url,
                            "content_type": "json",
                            "secret": webhook_secret,
                            "insecure_ssl": "0",
                        },
                    },
                )
            except httpx.HTTPError as exc:
                results.append({"repo": repo, "status": "failed", "detail": str(exc)[:160]})
                continue
            if resp.status_code in (200, 201):
                hook_id = resp.json().get("id")
                results.append({"repo": repo, "status": "registered", "hook_id": hook_id})
                if repo not in registered_repos:
                    registered_repos.append(repo)
            elif resp.status_code == 422:
                results.append({"repo": repo, "status": "already_exists", "detail": "Webhook already configured"})
                if repo not in registered_repos:
                    registered_repos.append(repo)
            else:
                detail = resp.text[:180]
                try:
                    detail = resp.json().get("message") or detail
                except Exception:
                    pass
                results.append({"repo": repo, "status": "failed", "code": resp.status_code, "detail": detail})

    if registered_repos:
        cfg["auto_webhook_registered"] = True
        cfg["auto_webhook_repos"] = registered_repos
        integ.config = cfg

    record_activity(
        db=db,
        action="integration.auto_webhook_attempted",
        entity_type="integration",
        entity_id=integ.id,
        user_id=current_user.id,
        project_id=integ.project_id,
        actor_email=current_user.email,
        details={"message": f"Registered webhook on {len(registered_repos)} GitHub repo(s) for {integ.name}"},
    )
    db.commit()

    return {
        "integration_id": integ.id,
        "provider": integ.provider,
        "mode": "github_api",
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret if secret_created else None,
        "has_secret": True,
        "results": results,
    }


@router.post("/{integration_id}/disconnect")
def disconnect_integration(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)

    integ.status = "disconnected"
    integ.auth_status = "revoked"
    integ.credentials = {}
    record_activity(
        db=db,
        action="integration.disconnected",
        entity_type="integration",
        entity_id=integ.id,
        user_id=current_user.id,
        project_id=integ.project_id,
        actor_email=current_user.email,
        details={"message": f"Disconnected {integ.name} and cleared credentials"},
    )
    db.commit()
    return {"status": "success", "message": f"Integration '{integ.name}' disconnected and credentials revoked."}


@router.post("/{integration_id}/reconnect", response_model=IntegrationResponse)
def reconnect_integration(
    integration_id: str,
    req: ReconnectRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_write=True)

    creds_to_check = req.credentials or decrypt_credentials(integ.credentials)
    token = _token_from_dict(creds_to_check)
    connector_cls = get_connector_class(integ.provider)
    if connector_cls:
        if not token:
            raise HTTPException(status_code=400, detail="Valid credentials are required to reconnect.")
        check = _build_connector(connector_cls, token=token, creds=creds_to_check).check_connection()
        if check.get("status") != "connected":
            raise HTTPException(status_code=400, detail=f"Reconnection auth failed: {check.get('message')}")
        integ.auth_status = "verified"
        integ.connected_account = check.get("connected_account") or integ.connected_account
        integ.scopes = check.get("scopes") or integ.scopes

    if req.credentials:
        integ.credentials = encrypt_credentials(req.credentials)
    if req.config is not None:
        integ.config = req.config
    integ.status = "connected"
    integ.error_message = None
    integ.last_sync = datetime.now(timezone.utc)
    db.commit()
    db.refresh(integ)
    return _to_response(integ)


@router.delete("/{integration_id}")
def delete_integration(
    integration_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    integ = db.query(Integration).filter(Integration.id == integration_id).first()
    if not integ:
        raise HTTPException(status_code=404, detail="Integration not found")
    verify_project_access(integ.project_id, current_user, db, require_admin=True)

    name = integ.name
    record_activity(
        db=db,
        action="integration.deleted",
        entity_type="integration",
        entity_id=integ.id,
        user_id=current_user.id,
        project_id=integ.project_id,
        actor_email=current_user.email,
        details={"message": f"Deleted integration '{name}'"},
    )
    db.delete(integ)
    db.commit()
    return {"status": "success", "message": f"Integration '{name}' deleted."}
