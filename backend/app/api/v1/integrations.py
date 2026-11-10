import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
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
    ConnectorError,
    GitHubConnector,
    NotionConnector,
    SlackConnector,
    get_connector_class,
)
from app.services.ingestion_service import upsert_source_records
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

router = APIRouter(prefix="/integrations", tags=["Source Connections"])


class ReconnectRequest(BaseModel):
    credentials: Optional[Dict[str, Any]] = None
    config: Optional[Dict[str, Any]] = None


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, Any]
    name: Optional[str] = None


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


def _extract_token(integ: Integration) -> Optional[str]:
    creds = decrypt_credentials(integ.credentials)
    token = creds.get("access_token") or creds.get("token") or creds.get("api_key") or creds.get("bot_token")
    if token:
        return token
    provider = (integ.provider or "").lower()
    if "github" in provider:
        return settings.GITHUB_TOKEN or os.getenv("GITHUB_TOKEN")
    if "slack" in provider:
        return settings.SLACK_BOT_TOKEN or os.getenv("SLACK_BOT_TOKEN")
    if "notion" in provider:
        return settings.NOTION_API_KEY or os.getenv("NOTION_API_KEY")
    return None


def _resolve_backend_base_url(request: Request) -> str:
    """Resolve external backend base URL cleanly in local dev and reverse-proxied cloud environments."""
    configured = (settings.BACKEND_URL or "").strip().rstrip("/")
    if configured and not configured.startswith("http://localhost") and not configured.startswith("http://127.0.0.1"):
        return configured
    forwarded_host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    if forwarded_host:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        if not forwarded_host.startswith("localhost") and not forwarded_host.startswith("127.0.0.1"):
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
        return RedirectResponse(f"{settings.FRONTEND_URL}/integrations?oauth_error={error}")
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code or state parameter.")

    payload = decode_access_token(state)
    if not payload or payload.get("token_type") != "oauth_state":
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state token.")

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
        conn = connector_cls(token=token)
        check = conn.check_connection()
        if check.get("status") != "connected":
            raise ConnectorError(check.get("message", "Provider connection check failed."))
    except ConnectorError as exc:
        return RedirectResponse(f"{settings.FRONTEND_URL}/integrations?oauth_error={str(exc)}")

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
    return RedirectResponse(f"{settings.FRONTEND_URL}/integrations?connected={provider.lower()}")


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


@router.post("", response_model=IntegrationResponse)
def create_integration(
    integ_in: IntegrationCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    verify_project_access(integ_in.project_id, current_user, db, require_write=True)

    provider = (integ_in.provider or "").lower()
    raw_creds = integ_in.credentials or {}
    token = raw_creds.get("access_token") or raw_creds.get("token") or raw_creds.get("api_key")

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
        check = connector_cls(token=token).check_connection()
        if check.get("status") != "connected":
            raise HTTPException(
                status_code=400,
                detail=f"{provider.title()} authentication failed: {check.get('message', 'Invalid credentials')}",
            )
        auth_status = "verified"
        connected_account = check.get("connected_account") or check.get("login") or check.get("team") or check.get("bot_name")
        scopes = check.get("scopes") or []

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

    token = _extract_token(integ)
    check = connector_cls(token=token).check_connection()
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
    integ.config = req.config or {}
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

    connector = connector_cls(token=token)
    try:
        synced_records, new_cursor = connector.sync(config=integ.config or {}, sync_cursor=integ.sync_cursor or {})
    except ConnectorError as exc:
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
    integ.sync_cursor = new_cursor
    integ.status = "connected"
    integ.auth_status = "verified"
    integ.error_message = None
    integ.last_sync = datetime.now(timezone.utc)
    db.commit()

    extracted = {}
    if extract_knowledge and (counts["added"] > 0 or counts["updated"] > 0):
        extracted = extract_and_persist_project_knowledge(db, integ.project_id, actor_user_id=current_user.id)

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
        },
    )


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
    token = creds_to_check.get("access_token") or creds_to_check.get("token") or creds_to_check.get("api_key")
    connector_cls = get_connector_class(integ.provider)
    if connector_cls:
        if not token:
            raise HTTPException(status_code=400, detail="Valid credentials are required to reconnect.")
        check = connector_cls(token=token).check_connection()
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
