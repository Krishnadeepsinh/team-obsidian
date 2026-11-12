import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.security import decrypt_credentials
from app.models.integration import Integration, SourceEvent
from app.services.connectors.base import compute_sha256
from app.services.drift_detector import scan_project_for_drift
from app.services.ingestion_service import upsert_source_records
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

logger = logging.getLogger("team_obsidian.webhooks")
router = APIRouter(prefix="/webhooks", tags=["Realtime Webhooks"])


def _verify_sha256_signature(secret: str, raw_body: bytes, signature_header: Optional[str], prefix: str = "sha256=") -> bool:
    if not secret or not signature_header:
        return False
    sig = signature_header.strip()
    if prefix and sig.startswith(prefix):
        sig = sig[len(prefix):]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)


def _get_webhook_secret(integ: Integration) -> str:
    creds = decrypt_credentials(integ.credentials)
    return str(creds.get("webhook_secret") or "").strip()


def _run_webhook_pipeline(project_id: str, integration_id: str) -> None:
    db = SessionLocal()
    try:
        extract_and_persist_project_knowledge(db, project_id)
        scan_project_for_drift(db, project_id)
    except Exception as exc:
        db.rollback()
        logger.warning("Background webhook processing error for %s: %s", integration_id, str(exc)[:140])
    finally:
        db.close()


@router.post("/github/{integration_id}")
async def github_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed GitHub webhook events (push, pull_request, issues), ingest delta, and run drift scan."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "github").first()
    if not integ:
        raise HTTPException(status_code=404, detail="GitHub integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Webhook secret is not configured for this integration.")
    sig_header = request.headers.get("X-Hub-Signature-256")
    if not _verify_sha256_signature(secret, raw_body, sig_header, prefix="sha256="):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook HMAC-SHA256 signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON webhook payload.")

    event_name = (request.headers.get("X-GitHub-Event") or "push").lower()
    repo_name = (payload.get("repository") or {}).get("full_name") or integ.name
    now = datetime.now(timezone.utc)
    records: List[Dict[str, Any]] = []

    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        pr_num = pr.get("number") or payload.get("number")
        title = pr.get("title") or f"PR #{pr_num}"
        author = (pr.get("user") or {}).get("login") or "github-user"
        state = "merged" if pr.get("merged") else pr.get("state", "updated")
        content = (
            f"PR #{pr_num}: {title}\n"
            f"Repository: {repo_name} | Action: {payload.get('action')} | State: {state} | Author: {author}\n\n"
            f"{pr.get('body') or ''}"
        )
        records.append({
            "source_type": "github_pr",
            "external_id": f"{repo_name}#pr-{pr.get('id') or pr_num}",
            "title": f"PR #{pr_num}: {title}",
            "author": author,
            "url": pr.get("html_url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "webhook_event": "pull_request", "action": payload.get("action")},
            "raw_payload": payload,
        })
    elif event_name == "issues":
        issue = payload.get("issue") or {}
        num = issue.get("number")
        author = (issue.get("user") or {}).get("login") or "github-user"
        content = (
            f"Issue #{num}: {issue.get('title')}\n"
            f"Repository: {repo_name} | Action: {payload.get('action')} | Author: {author}\n\n"
            f"{issue.get('body') or ''}"
        )
        records.append({
            "source_type": "github_issue",
            "external_id": f"{repo_name}#issue-{issue.get('id') or num}",
            "title": f"Issue #{num}: {issue.get('title')}",
            "author": author,
            "url": issue.get("html_url"),
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": now,
            "metadata": {"repository": repo_name, "webhook_event": "issues", "action": payload.get("action")},
            "raw_payload": payload,
        })
    elif event_name == "push":
        for c in (payload.get("commits") or [])[:15]:
            sha = c.get("id") or c.get("sha") or compute_sha256(json.dumps(c))[:12]
            msg = c.get("message") or "Commit push"
            author = (c.get("author") or {}).get("name") or (payload.get("pusher") or {}).get("name") or "committer"
            modified = ", ".join((c.get("modified") or []) + (c.get("added") or []) + (c.get("removed") or []))
            content = (
                f"Commit {sha[:10]} in {repo_name} (ref {payload.get('ref', 'main')}): {msg}\n"
                f"Author: {author}\n"
                f"Files Touched: {modified or 'n/a'}"
            )
            records.append({
                "source_type": "github_commit",
                "external_id": f"{repo_name}#commit-{sha}",
                "title": f"Commit {sha[:8]}: {msg.splitlines()[0][:120]}",
                "author": author,
                "url": c.get("url"),
                "content": content,
                "sha256": compute_sha256(content),
                "source_timestamp": now,
                "metadata": {"repository": repo_name, "webhook_event": "push", "ref": payload.get("ref")},
                "raw_payload": c,
            })

    counts = {"added": 0, "updated": 0, "skipped": 0}
    if records:
        counts = upsert_source_records(db=db, integration=integ, raw_records=records)

    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "github", "event": event_name, "repository": repo_name},
        )
    )
    integ.last_sync = now
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id) if records else {"detected": 0, "events": []}
    if records:
        background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)

    return {
        "status": "accepted",
        "event": event_name,
        "records": counts,
        "drift_detected": drift_summary.get("detected", 0),
    }


@router.post("/slack/{integration_id}")
async def slack_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive Slack Events API callbacks (supports url_verification + signed X-Slack-Signature ingestion)."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "slack").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Slack integration not found")

    raw_body = await request.body()
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Slack webhook payload.")

    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Slack signing webhook secret is not configured.")

    ts = request.headers.get("X-Slack-Request-Timestamp") or ""
    sig = request.headers.get("X-Slack-Signature") or ""
    base_str = f"v0:{ts}:{raw_body.decode('utf-8', errors='replace')}".encode("utf-8")
    expected = "v0=" + hmac.new(secret.encode("utf-8"), base_str, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(expected, sig):
        raise HTTPException(status_code=401, detail="Invalid Slack webhook signature.")

    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    event = payload.get("event") or {}
    text_msg = (event.get("text") or "").strip()
    records: List[Dict[str, Any]] = []
    if text_msg:
        channel_id = event.get("channel") or "slack-channel"
        msg_ts = event.get("ts") or compute_sha256(text_msg)[:12]
        user_id = event.get("user") or "slack-member"
        content = f"Slack realtime message in #{channel_id} by {user_id}:\n{text_msg}"
        records.append({
            "source_type": "slack_message",
            "external_id": f"{channel_id}#msg-{msg_ts}",
            "title": f"Slack #{channel_id}: {text_msg[:80]}",
            "author": user_id,
            "content": content,
            "sha256": compute_sha256(content),
            "source_timestamp": datetime.now(timezone.utc),
            "metadata": {"channel_id": channel_id, "webhook_event": event.get("type")},
            "raw_payload": event,
        })

    counts = upsert_source_records(db=db, integration=integ, raw_records=records) if records else {"added": 0, "updated": 0, "skipped": 0}
    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "slack", "event_type": event.get("type")},
        )
    )
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id) if records else {"detected": 0}
    if records:
        background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)

    return {"status": "accepted", "records": counts, "drift_detected": drift_summary.get("detected", 0)}


@router.post("/notion/{integration_id}")
async def notion_webhook(
    integration_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Receive signed Notion webhook events for real-time page/database updates."""
    integ = db.query(Integration).filter(Integration.id == integration_id, Integration.provider == "notion").first()
    if not integ:
        raise HTTPException(status_code=404, detail="Notion integration not found")

    raw_body = await request.body()
    secret = _get_webhook_secret(integ)
    if not secret:
        raise HTTPException(status_code=403, detail="Notion webhook secret is not configured.")
    sig = request.headers.get("X-Notion-Signature")
    if not _verify_sha256_signature(secret, raw_body, sig, prefix="sha256="):
        raise HTTPException(status_code=401, detail="Invalid Notion webhook signature.")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Notion webhook payload.")

    entity = payload.get("entity") or payload
    page_id = str(entity.get("id") or payload.get("id") or compute_sha256(raw_body.decode("utf-8", errors="replace"))[:12])
    title = payload.get("title") or f"Notion Page {page_id[:8]}"
    body_text = payload.get("content") or payload.get("summary") or f"Notion webhook update ({payload.get('type', 'page.updated')}) for {title}"

    rec = {
        "source_type": "notion_page",
        "external_id": f"notion#{page_id}",
        "title": title[:500],
        "author": payload.get("actor_name") or "Notion Collaborator",
        "url": payload.get("url"),
        "content": body_text,
        "sha256": compute_sha256(body_text),
        "source_timestamp": datetime.now(timezone.utc),
        "metadata": {"page_id": page_id, "webhook_event": payload.get("type", "page.updated")},
        "raw_payload": payload,
    }
    counts = upsert_source_records(db=db, integration=integ, raw_records=[rec])
    db.add(
        SourceEvent(
            integration_id=integ.id,
            event_type="webhook_received",
            status="success",
            records_added=counts["added"],
            records_updated=counts["updated"],
            records_skipped=counts["skipped"],
            details={"provider": "notion", "page_id": page_id},
        )
    )
    db.commit()

    drift_summary = scan_project_for_drift(db, integ.project_id)
    background_tasks.add_task(_run_webhook_pipeline, integ.project_id, integ.id)
    return {"status": "accepted", "records": counts, "drift_detected": drift_summary.get("detected", 0)}

