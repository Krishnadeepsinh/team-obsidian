import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.evidence import Evidence
from app.models.handover import Handover, HandoverClaim
from app.models.integration import SourceRecord
from app.models.knowledge import Decision, Dependency, KnowledgeDriftEvent, RiskItem
from app.models.workspace import Notification, Project, ProjectMember, User, Workspace
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity
from app.services.email_service import email_service


def _coerce_utc_naive(dt: Any) -> Optional[datetime]:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    if isinstance(dt, str):
        try:
            parsed = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            return None
    return None


def _is_source_newer_than_target(src: SourceRecord, target_ts: Any) -> bool:
    """Return True when source event occurred at/after target baseline (or dates unavailable)."""
    src_dt = _coerce_utc_naive(src.source_timestamp or src.updated_at or src.ingested_at)
    tgt_dt = _coerce_utc_naive(target_ts)
    if not src_dt or not tgt_dt:
        return True
    return src_dt >= tgt_dt


def _semantic_similarity(text_a: str, text_b: str, vec_cache: Dict[str, List[float]]) -> float:
    """Compute cached SEMANTIC_SIMILARITY cosine score between source snippet and claim/decision."""
    a_key = (text_a or "")[:600].strip()
    b_key = (text_b or "")[:600].strip()
    if not a_key or not b_key:
        return 0.0
    if a_key not in vec_cache:
        vec_cache[a_key] = ai_engine.generate_embedding(a_key, task_type="SEMANTIC_SIMILARITY")
    if b_key not in vec_cache:
        vec_cache[b_key] = ai_engine.generate_embedding(b_key, task_type="SEMANTIC_SIMILARITY")
    return float(ai_engine.cosine_similarity(vec_cache[a_key], vec_cache[b_key]))

logger = logging.getLogger("team_obsidian.drift")

_STOPWORDS = {
    "about", "after", "again", "against", "all", "also", "and", "another", "any", "are", "because",
    "been", "before", "being", "between", "both", "but", "could", "does", "during", "each", "from",
    "have", "having", "into", "more", "most", "need", "other", "should", "since", "some", "such",
    "than", "that", "their", "there", "these", "they", "this", "those", "through", "under", "until",
    "using", "very", "what", "when", "where", "which", "while", "with", "would",
}

_CHANGE_SIGNALS = re.compile(
    r"\b(deprecat\w*|replac\w*|migrat\w*|remov\w*|sunset\w*|reverted|rollback|switched\s+from|"
    r"supersed\w*|obsolete|contradict\w*|breaking\s+change|no\s+longer\s+use|decommission\w*)\b",
    re.I,
)

_OWNERSHIP_SIGNALS = re.compile(
    r"\b(reassigned|new\s+owner|handover\s+to|transferred\s+ownership|stepping\s+down|leaving)\b",
    re.I,
)


def _keywords(text: str) -> Set[str]:
    tokens = re.findall(r"[a-zA-Z0-9_-]{4,}", (text or "").lower())
    return {t for t in tokens if t not in _STOPWORDS}


def scan_project_for_drift(
    db: Session,
    project_id: str,
    actor_user_id: Optional[str] = None,
    max_sources: int = 25,
) -> Dict[str, Any]:
    """Detect contradictions, superseded decisions, ownership shifts, and stale claims across synced sources."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"detected": 0, "events": []}

    recent_sources = (
        db.query(SourceRecord)
        .filter(SourceRecord.project_id == project_id)
        .order_by(SourceRecord.ingested_at.desc())
        .limit(max_sources)
        .all()
    )
    if not recent_sources:
        return {"detected": 0, "events": []}

    decisions = db.query(Decision).filter(Decision.project_id == project_id).all()
    dependencies = db.query(Dependency).filter(Dependency.project_id == project_id).all()
    risks = db.query(RiskItem).filter(RiskItem.project_id == project_id).all()
    claims = (
        db.query(HandoverClaim)
        .join(HandoverClaim.handover)
        .filter(HandoverClaim.handover.has(project_id=project_id))
        .all()
    )

    existing_open = {
        (e.target_entity_type, e.target_entity_id, e.source_record_id or "")
        for e in db.query(KnowledgeDriftEvent)
        .filter(KnowledgeDriftEvent.project_id == project_id, KnowledgeDriftEvent.status.in_(["open", "acknowledged"]))
        .all()
    }

    created_events: List[KnowledgeDriftEvent] = []

    def _add_drift(
        source: SourceRecord,
        drift_type: str,
        severity: str,
        target_type: str,
        target_id: str,
        target_title: str,
        summary: str,
    ) -> None:
        dedup_key = (target_type, target_id, source.id)
        if dedup_key in existing_open:
            return
        existing_open.add(dedup_key)
        ev = KnowledgeDriftEvent(
            project_id=project_id,
            integration_id=source.integration_id,
            source_record_id=source.id,
            drift_type=drift_type,
            severity=severity,
            target_entity_type=target_type,
            target_entity_id=target_id,
            target_title=target_title[:500],
            summary=summary,
            evidence_excerpt=(source.content or "")[:600],
            status="open",
            metadata_json={
                "source_title": source.title,
                "source_type": source.source_type,
                "source_url": source.url,
                "sha256": source.sha256_hash,
            },
        )
        db.add(ev)
        created_events.append(ev)

    for src in recent_sources:
        src_text = f"{src.title or ''}\n{src.content or ''}"
        has_change = bool(_CHANGE_SIGNALS.search(src_text))
        has_owner_shift = bool(_OWNERSHIP_SIGNALS.search(src_text))
        if not has_change and not has_owner_shift:
            continue
        src_kw = _keywords(src_text)

        # 1. Check ADRs / Decisions for contradictions or deprecation
        for dec in decisions:
            dec_kw = _keywords(f"{dec.title} {dec.component or ''} {dec.summary}")
            overlap = src_kw & dec_kw
            if len(overlap) >= 2 or (dec.component and dec.component.lower() in src_text.lower() and has_change):
                drift_kind = "superseded" if re.search(r"\b(replac|migrat|supersed|switched)\b", src_text, re.I) else "contradiction"
                _add_drift(
                    src,
                    drift_kind,
                    "critical" if dec.status == "accepted" else "high",
                    "decision",
                    dec.id,
                    dec.title,
                    f"Recent source '{src.title}' indicates changes ({', '.join(sorted(overlap)[:4])}) affecting accepted decision '{dec.title}'.",
                )

        # 2. Check Dependencies for replacement/removal shifts
        for dep in dependencies:
            src_comp = (dep.source_component or "").lower()
            dst_comp = (dep.target_component or "").lower()
            if ((src_comp and len(src_comp) > 2 and src_comp in src_text.lower())
                    or (dst_comp and len(dst_comp) > 2 and dst_comp in src_text.lower())) and has_change:
                _add_drift(
                    src,
                    "dependency_shift",
                    "high",
                    "dependency",
                    dep.id,
                    f"{dep.source_component} -> {dep.target_component}",
                    f"Source '{src.title}' references deprecation or migration impacting dependency {dep.source_component} -> {dep.target_component}.",
                )

        # 3. Check Ownership / Risk updates
        for rsk in risks:
            if rsk.owner and rsk.owner.lower() in src_text.lower() and has_owner_shift:
                _add_drift(
                    src,
                    "ownership_change",
                    "medium",
                    "risk",
                    rsk.id,
                    rsk.title,
                    f"Source '{src.title}' notes ownership transition involving '{rsk.owner}' on risk '{rsk.title}'.",
                )

        # 4. Check Handover Claims (semantic + lexical + temporal guard) & flag Contradicted
        _vec_cache: Dict[str, List[float]] = {}
        invalidated_handovers: Set[str] = set()
        for cl in claims:
            if not _is_source_newer_than_target(src, getattr(cl, "updated_at", None) or getattr(cl, "created_at", None)):
                continue
            cl_kw = _keywords(cl.claim_text)
            overlap = src_kw & cl_kw
            sem_sim = 0.0
            if len(overlap) < 3 and has_change and len(overlap) >= 1:
                sem_sim = _semantic_similarity(src_text[:600], cl.claim_text, _vec_cache)
            elif len(overlap) == 0 and has_change and len(cl.claim_text or "") >= 25:
                sem_sim = _semantic_similarity(src_text[:600], cl.claim_text, _vec_cache)

            is_semantic_hit = sem_sim >= 0.66
            if (len(overlap) >= 3 or is_semantic_hit) and has_change:
                signal_desc = (
                    f"semantic={sem_sim:.2f}" if is_semantic_hit else ", ".join(sorted(overlap)[:4])
                )
                _add_drift(
                    src,
                    "doc_stale",
                    "high",
                    "handover_claim",
                    cl.id,
                    cl.claim_text[:180],
                    f"New update '{src.title}' contradicts handover claim ({signal_desc}).",
                )
                if cl.verification_status not in ("Contradicted", "Rejected"):
                    cl.verification_status = "Contradicted"
                    cl.review_notes = (
                        f"Auto-flagged by Semantic+Temporal Drift Detector from '{src.title}' ({signal_desc})."
                    )
                    if cl.handover_id:
                        invalidated_handovers.add(cl.handover_id)

        if invalidated_handovers:
            db.flush()
            for ho in db.query(Handover).filter(Handover.id.in_(list(invalidated_handovers))).all():
                stats = dict(ho.reconstruction_stats or {})
                contradicted_cnt = (
                    db.query(HandoverClaim)
                    .filter(
                        HandoverClaim.handover_id == ho.id,
                        HandoverClaim.verification_status == "Contradicted",
                    )
                    .count()
                )
                stats["has_drift_warning"] = True
                stats["drift_invalidated_claims"] = contradicted_cnt
                ho.reconstruction_stats = stats

        # Flag source's linked evidence if critical change was detected
        if has_change:
            ev_row = db.query(Evidence).filter(Evidence.source_record_id == src.id).first()
            if ev_row and ev_row.verification_status == "Needs Human Verification":
                ev_row.ai_interpretation = (
                    f"[Drift Signal] {ev_row.ai_interpretation or src.title}"
                )[:800]

    if created_events:
        db.flush()
        record_activity(
            db=db,
            action="knowledge.drift_detected",
            entity_type="knowledge_drift",
            entity_id=created_events[0].id,
            user_id=actor_user_id,
            project_id=project_id,
            details={"message": f"Detected {len(created_events)} knowledge drift alert(s) in {project.name}"},
        )
        # In-app notification + optional email alert to project owner
        owner = db.query(User).filter(User.id == project.creator_id).first() if project.creator_id else None
        if owner is None:
            pm = (
                db.query(ProjectMember)
                .filter(
                    ProjectMember.project_id == project_id,
                    ProjectMember.project_role.in_(["project_owner", "workspace_owner", "org_admin", "tech_lead"]),
                )
                .first()
            )
            if pm:
                owner = db.query(User).filter(User.id == pm.user_id).first()
        if owner is None and project.workspace_id:
            ws = db.query(Workspace).filter(Workspace.id == project.workspace_id).first()
            if ws and ws.owner_id:
                owner = db.query(User).filter(User.id == ws.owner_id).first()
        if owner is None and actor_user_id:
            owner = db.query(User).filter(User.id == actor_user_id).first()
        if owner:
            db.add(
                Notification(
                    user_id=owner.id,
                    project_id=project_id,
                    title=f"Knowledge Drift Alert ({len(created_events)} detected)",
                    message=created_events[0].summary[:300],
                    type="warning",
                    link="/evidence",
                )
            )
            try:
                email_service.send_drift_alert_email(
                    to_email=owner.email,
                    recipient_name=owner.name or owner.email,
                    project_name=project.name,
                    target_title=created_events[0].target_title,
                    drift_summary=created_events[0].summary,
                    severity=created_events[0].severity,
                )
            except Exception as exc:
                logger.warning("Drift alert email failed: %s", exc)
        db.commit()

    return {
        "detected": len(created_events),
        "events": [
            {
                "id": e.id,
                "drift_type": e.drift_type,
                "severity": e.severity,
                "target_entity_type": e.target_entity_type,
                "target_title": e.target_title,
                "summary": e.summary,
                "status": e.status,
            }
            for e in created_events
        ],
    }

