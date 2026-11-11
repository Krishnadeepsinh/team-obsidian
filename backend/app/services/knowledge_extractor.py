from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session


def _s(val: Optional[str], max_len: Optional[int] = None, default: str = "") -> str:
    cleaned = (val or default).replace("\x00", "").strip()
    if max_len is not None:
        return cleaned[:max_len]
    return cleaned

from app.models.evidence import Evidence
from app.models.integration import SourceRecord
from app.models.knowledge import (
    Decision,
    Dependency,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.models.workspace import Project
from app.services.ai_engine import ai_engine
from app.services.audit_service import record_activity

logger = logging.getLogger("team_obsidian.extractor")


def extract_and_persist_project_knowledge(
    db: Session,
    project_id: str,
    actor_user_id: Optional[str] = None,
    max_records: int = 15,
) -> Dict[str, int]:
    """Extract structured entities, relationships, decisions, tasks, risks, dependencies, and gaps from project evidence."""
    proj = db.query(Project).filter(Project.id == project_id).first()
    project_name = proj.name if proj else "Project"

    evidences = (
        db.query(Evidence)
        .filter(Evidence.project_id == project_id)
        .order_by(Evidence.created_at.desc())
        .limit(max_records)
        .all()
    )
    if not evidences:
        return {"entities": 0, "relationships": 0, "decisions": 0, "tasks": 0, "risks": 0, "dependencies": 0, "gaps": 0}

    records_payload: List[Dict[str, Any]] = []
    for ev in evidences:
        records_payload.append({
            "evidence_id": ev.id,
            "source_record_id": ev.source_record_id,
            "title": ev.source_title,
            "source_type": ev.source_type,
            "author": ev.source_author,
            "date": ev.source_timestamp.isoformat() if ev.source_timestamp else ev.created_at.isoformat(),
            "content": ev.excerpt,
        })

    bundle = ai_engine.extract_knowledge_from_records(records_payload, project_name=project_name)
    counts = {"entities": 0, "relationships": 0, "decisions": 0, "tasks": 0, "risks": 0, "dependencies": 0, "gaps": 0}

    def _ev_for(idx: int) -> Optional[Evidence]:
        if 1 <= idx <= len(evidences):
            return evidences[idx - 1]
        return evidences[0] if evidences else None

    # 1. Entities (deduplicate by lowercased name within project)
    entity_map: Dict[str, KnowledgeEntity] = {
        e.name.strip().lower(): e
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
    }
    for item in bundle.entities:
        key = _s(item.name).lower()
        if not key or key in entity_map:
            continue
        ev = _ev_for(item.evidence_index)
        ke = KnowledgeEntity(
            project_id=project_id,
            created_by_user_id=actor_user_id,
            source_record_id=ev.source_record_id if ev else None,
            entity_type=_s(item.entity_type, 50, "component") or "component",
            name=_s(item.name, 255),
            description=_s(item.description),
            properties={"owner": _s(item.owner, 255)} if item.owner else {},
            confidence=0.75 if ev else 0.4,
            verification_status="Draft / AI Suggested",
            evidence_id=ev.id if ev else None,
        )
        db.add(ke)
        db.flush()
        entity_map[key] = ke
        counts["entities"] += 1

    # 2. Relationships
    for rel in bundle.relationships:
        src = entity_map.get(_s(rel.source_name).lower())
        dst = entity_map.get(_s(rel.target_name).lower())
        rel_type = _s(rel.relation_type, 50, "relates_to") or "relates_to"
        if not src or not dst or src.id == dst.id:
            continue
        exists = (
            db.query(KnowledgeRelationship)
            .filter(
                KnowledgeRelationship.project_id == project_id,
                KnowledgeRelationship.source_entity_id == src.id,
                KnowledgeRelationship.target_entity_id == dst.id,
                KnowledgeRelationship.relation_type == rel_type,
            )
            .first()
        )
        if exists:
            continue
        ev = _ev_for(rel.evidence_index)
        db.add(
            KnowledgeRelationship(
                project_id=project_id,
                source_entity_id=src.id,
                target_entity_id=dst.id,
                relation_type=rel_type,
                context=_s(rel.context),
                confidence=0.75 if ev else 0.4,
                verification_status="Draft / AI Suggested",
                evidence_id=ev.id if ev else None,
                source_record_id=ev.source_record_id if ev else None,
            )
        )
        counts["relationships"] += 1

    # 3. Decisions
    existing_decs = {
        d.title.strip().lower()
        for d in db.query(Decision).filter(Decision.project_id == project_id).all()
    }
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for dec in bundle.decisions:
        dec_title = _s(dec.title, 500)
        if not dec_title or dec_title.lower() in existing_decs:
            continue
        ev = _ev_for(dec.evidence_index)
        db.add(
            Decision(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=dec_title,
                summary=_s(dec.summary) or dec_title,
                reasoning=_s(dec.reasoning) or _s(dec.summary) or dec_title,
                decision_maker=_s(dec.decision_maker, 255, "Contributor") or "Contributor",
                date=_s(dec.date, 50) or (ev.created_at.strftime("%Y-%m-%d") if ev else today_str),
                component=_s(dec.component, 255) or None,
                decision_type=_s(dec.decision_type, 50, "technical") or "technical",
                status="accepted",
                verification_status="Draft / AI Suggested",
                alternatives=dec.alternatives or [],
                tradeoffs=dec.tradeoffs or [],
                consequences=dec.consequences or [],
                confidence=0.75 if ev else 0.4,
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_decs.add(dec_title.lower())
        counts["decisions"] += 1

    # 4. Tasks
    existing_tasks = {
        t.title.strip().lower()
        for t in db.query(TaskItem).filter(TaskItem.project_id == project_id).all()
    }
    for t in bundle.tasks:
        task_title = _s(t.title, 500)
        if not task_title or task_title.lower() in existing_tasks:
            continue
        ev = _ev_for(t.evidence_index)
        raw_prio = _s(t.priority, 20).lower()
        raw_status = _s(t.status, 50).lower()
        db.add(
            TaskItem(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=task_title,
                description=_s(t.description),
                owner=_s(t.owner, 255, "Unassigned") or "Unassigned",
                component=_s(t.component, 255) or None,
                priority=raw_prio if raw_prio in ("critical", "high", "medium", "low") else "medium",
                status=raw_status if raw_status in ("open", "in_progress", "blocked", "completed") else "open",
                deadline=_s(t.deadline, 50) or None,
                verification_status="Draft / AI Suggested",
                confidence=0.72 if ev else 0.4,
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_tasks.add(task_title.lower())
        counts["tasks"] += 1

    # 5. Risks
    existing_risks = {
        r.title.strip().lower()
        for r in db.query(RiskItem).filter(RiskItem.project_id == project_id).all()
    }
    for r in bundle.risks:
        risk_title = _s(r.title, 500)
        if not risk_title or risk_title.lower() in existing_risks:
            continue
        ev = _ev_for(r.evidence_index)
        raw_sev = _s(r.severity, 20).lower()
        raw_like = _s(r.likelihood, 20).lower()
        db.add(
            RiskItem(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=risk_title,
                description=_s(r.description) or risk_title,
                category=_s(r.category, 50, "technical_risk") or "technical_risk",
                severity=raw_sev if raw_sev in ("critical", "high", "medium", "low") else "high",
                likelihood=raw_like if raw_like in ("high", "medium", "low") else "medium",
                impact=_s(r.impact) or None,
                owner=_s(r.owner, 255) or None,
                mitigation_strategy=_s(r.mitigation_strategy) or None,
                related_components=[_s(str(c), 255) for c in (r.related_components or []) if _s(str(c))],
                verification_status="Draft / AI Suggested",
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_risks.add(risk_title.lower())
        counts["risks"] += 1

    # 6. Dependencies
    existing_deps = {
        (d.source_component.lower(), d.target_component.lower())
        for d in db.query(Dependency).filter(Dependency.project_id == project_id).all()
    }
    for dep in bundle.dependencies:
        src_comp = _s(dep.source_component, 255)
        dst_comp = _s(dep.target_component, 255)
        pair = (src_comp.lower(), dst_comp.lower())
        if not pair[0] or not pair[1] or pair in existing_deps:
            continue
        ev = _ev_for(dep.evidence_index)
        raw_crit = _s(dep.criticality, 20, "high").lower() or "high"
        db.add(
            Dependency(
                project_id=project_id,
                source_component=src_comp,
                target_component=dst_comp,
                dependency_type=_s(dep.dependency_type, 50, "hard_blocker") or "hard_blocker",
                description=_s(dep.description) or None,
                owner=_s(dep.owner, 255) or None,
                criticality=raw_crit,
                verification_status="Draft / AI Suggested",
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_deps.add(pair)
        counts["dependencies"] += 1

    # 7. Responsibilities
    for resp in bundle.responsibilities:
        ev = _ev_for(resp.evidence_index)
        r_owner = _s(resp.owner, 255)
        r_domain = _s(resp.domain, 255)
        if not r_owner or not r_domain:
            continue
        exists = (
            db.query(Responsibility)
            .filter(
                Responsibility.project_id == project_id,
                Responsibility.owner == r_owner,
                Responsibility.domain == r_domain,
            )
            .first()
        )
        if not exists:
            db.add(
                Responsibility(
                    project_id=project_id,
                    owner=r_owner,
                    domain=r_domain,
                    scope=_s(resp.scope) or f"Ownership of {r_domain}",
                    criticality=_s(resp.criticality, 20, "high").lower() or "high",
                    backup_owner=_s(resp.backup_owner, 255) or None,
                    verification_status="Draft / AI Suggested",
                    evidence_ids=[ev.id] if ev else [],
                )
            )

    # 8. Knowledge Gaps
    existing_gaps = {
        g.title.strip().lower()
        for g in db.query(KnowledgeGap).filter(KnowledgeGap.project_id == project_id).all()
    }
    for gap in bundle.knowledge_gaps:
        gap_title = _s(gap.title, 500)
        if not gap_title or gap_title.lower() in existing_gaps:
            continue
        gap_sev = _s(gap.severity, 20, "high").lower() or "high"
        gap_impact = _s(gap.business_impact) or _s(gap.technical_impact) or _s(gap.description) or gap_title
        db.add(
            KnowledgeGap(
                project_id=project_id,
                title=gap_title,
                description=_s(gap.description) or gap_title,
                gap_type=_s(gap.gap_type, 50, "missing_documentation") or "missing_documentation",
                severity=gap_sev,
                priority=gap_sev,
                impact=gap_impact,
                business_impact=_s(gap.business_impact) or None,
                technical_impact=_s(gap.technical_impact) or None,
                recommended_action=_s(gap.recommended_action) or "Document and assign an owner during handover review.",
            )
        )
        existing_gaps.add(gap_title.lower())
        counts["gaps"] += 1

    record_activity(
        db=db,
        action="knowledge.extracted",
        entity_type="project",
        entity_id=project_id,
        user_id=actor_user_id,
        project_id=project_id,
        details={"message": "AI extracted structured project knowledge", "counts": counts},
    )
    db.commit()
    return counts

