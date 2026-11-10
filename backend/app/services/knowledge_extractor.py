import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

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
        key = item.name.strip().lower()
        if not key or key in entity_map:
            continue
        ev = _ev_for(item.evidence_index)
        ke = KnowledgeEntity(
            project_id=project_id,
            created_by_user_id=actor_user_id,
            source_record_id=ev.source_record_id if ev else None,
            entity_type=item.entity_type,
            name=item.name.strip()[:255],
            description=item.description or "",
            properties={"owner": item.owner} if item.owner else {},
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
        src = entity_map.get(rel.source_name.strip().lower())
        dst = entity_map.get(rel.target_name.strip().lower())
        if not src or not dst or src.id == dst.id:
            continue
        exists = (
            db.query(KnowledgeRelationship)
            .filter(
                KnowledgeRelationship.project_id == project_id,
                KnowledgeRelationship.source_entity_id == src.id,
                KnowledgeRelationship.target_entity_id == dst.id,
                KnowledgeRelationship.relation_type == rel.relation_type,
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
                relation_type=rel.relation_type,
                context=rel.context or "",
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
    for dec in bundle.decisions:
        if not dec.title.strip() or dec.title.strip().lower() in existing_decs:
            continue
        ev = _ev_for(dec.evidence_index)
        db.add(
            Decision(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=dec.title.strip()[:500],
                summary=dec.summary,
                reasoning=dec.reasoning,
                decision_maker=dec.decision_maker or "Contributor",
                date=dec.date or (ev.created_at.strftime("%Y-%m-%d") if ev else "2026-11-10"),
                component=dec.component,
                decision_type=dec.decision_type,
                status="accepted",
                verification_status="Draft / AI Suggested",
                alternatives=dec.alternatives,
                tradeoffs=dec.tradeoffs,
                consequences=dec.consequences,
                confidence=0.75 if ev else 0.4,
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_decs.add(dec.title.strip().lower())
        counts["decisions"] += 1

    # 4. Tasks
    existing_tasks = {
        t.title.strip().lower()
        for t in db.query(TaskItem).filter(TaskItem.project_id == project_id).all()
    }
    for t in bundle.tasks:
        if not t.title.strip() or t.title.strip().lower() in existing_tasks:
            continue
        ev = _ev_for(t.evidence_index)
        db.add(
            TaskItem(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=t.title.strip()[:500],
                description=t.description,
                owner=t.owner or "Unassigned",
                component=t.component,
                priority=t.priority if t.priority in ("critical", "high", "medium", "low") else "medium",
                status=t.status if t.status in ("open", "in_progress", "blocked", "completed") else "open",
                deadline=t.deadline,
                verification_status="Draft / AI Suggested",
                confidence=0.72 if ev else 0.4,
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_tasks.add(t.title.strip().lower())
        counts["tasks"] += 1

    # 5. Risks
    existing_risks = {
        r.title.strip().lower()
        for r in db.query(RiskItem).filter(RiskItem.project_id == project_id).all()
    }
    for r in bundle.risks:
        if not r.title.strip() or r.title.strip().lower() in existing_risks:
            continue
        ev = _ev_for(r.evidence_index)
        db.add(
            RiskItem(
                project_id=project_id,
                created_by_user_id=actor_user_id,
                title=r.title.strip()[:500],
                description=r.description,
                category=r.category,
                severity=r.severity if r.severity in ("critical", "high", "medium", "low") else "high",
                likelihood=r.likelihood if r.likelihood in ("high", "medium", "low") else "medium",
                impact=r.impact,
                owner=r.owner,
                mitigation_strategy=r.mitigation_strategy,
                related_components=r.related_components,
                verification_status="Draft / AI Suggested",
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_risks.add(r.title.strip().lower())
        counts["risks"] += 1

    # 6. Dependencies
    existing_deps = {
        (d.source_component.lower(), d.target_component.lower())
        for d in db.query(Dependency).filter(Dependency.project_id == project_id).all()
    }
    for dep in bundle.dependencies:
        pair = (dep.source_component.strip().lower(), dep.target_component.strip().lower())
        if not pair[0] or not pair[1] or pair in existing_deps:
            continue
        ev = _ev_for(dep.evidence_index)
        db.add(
            Dependency(
                project_id=project_id,
                source_component=dep.source_component.strip()[:255],
                target_component=dep.target_component.strip()[:255],
                dependency_type=dep.dependency_type,
                description=dep.description,
                owner=dep.owner,
                criticality=dep.criticality,
                verification_status="Draft / AI Suggested",
                evidence_ids=[ev.id] if ev else [],
            )
        )
        existing_deps.add(pair)
        counts["dependencies"] += 1

    # 7. Responsibilities
    for resp in bundle.responsibilities:
        ev = _ev_for(resp.evidence_index)
        exists = (
            db.query(Responsibility)
            .filter(
                Responsibility.project_id == project_id,
                Responsibility.owner == resp.owner,
                Responsibility.domain == resp.domain,
            )
            .first()
        )
        if not exists:
            db.add(
                Responsibility(
                    project_id=project_id,
                    owner=resp.owner,
                    domain=resp.domain,
                    scope=resp.scope,
                    criticality=resp.criticality,
                    backup_owner=resp.backup_owner,
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
        if not gap.title.strip() or gap.title.strip().lower() in existing_gaps:
            continue
        db.add(
            KnowledgeGap(
                project_id=project_id,
                title=gap.title.strip()[:500],
                description=gap.description,
                gap_type=gap.gap_type,
                severity=gap.severity,
                priority=gap.severity,
                impact=gap.business_impact or gap.technical_impact,
                business_impact=gap.business_impact,
                technical_impact=gap.technical_impact,
                recommended_action=gap.recommended_action,
            )
        )
        existing_gaps.add(gap.title.strip().lower())
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

