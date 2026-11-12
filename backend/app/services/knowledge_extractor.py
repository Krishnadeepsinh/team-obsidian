"""Watermarked incremental knowledge extraction with identity resolution and bidirectional graph sync."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
from app.services.identity_resolver import (
    build_project_identity_map,
    merge_duplicate_person_entities,
    resolve_author_name,
)

logger = logging.getLogger("team_obsidian.extractor")


def _s(val: Optional[str], max_len: Optional[int] = None, default: str = "") -> str:
    cleaned = (val or default).replace("\x00", "").strip()
    if max_len is not None:
        return cleaned[:max_len]
    return cleaned


def _utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _needs_extraction(ev: Evidence, source_map: Dict[str, SourceRecord], force: bool) -> bool:
    if force:
        return True
    meta = ev.metadata_json or {}
    if ev.source_record_id and ev.source_record_id in source_map:
        sr = source_map[ev.source_record_id]
        if sr.extraction_processed_at is None:
            return True
        if sr.sha256_hash and meta.get("extracted_sha256") == sr.sha256_hash:
            return False
        if sr.updated_at and (sr.updated_at - sr.extraction_processed_at).total_seconds() > 2.0:
            return True
        return False
    return not bool(meta.get("extraction_processed_at"))


def extract_and_persist_project_knowledge(
    db: Session,
    project_id: str,
    actor_user_id: Optional[str] = None,
    max_records: int = 15,
    full_sweep: bool = True,
    force: bool = False,
) -> Dict[str, int]:
    """Incrementally extract structured entities, relationships, decisions, tasks, risks, dependencies, and gaps."""
    proj = db.query(Project).filter(Project.id == project_id).first()
    project_name = proj.name if proj else "Project"

    source_records = db.query(SourceRecord).filter(SourceRecord.project_id == project_id).all()
    source_map: Dict[str, SourceRecord] = {sr.id: sr for sr in source_records}

    all_evidences = (
        db.query(Evidence)
        .filter(Evidence.project_id == project_id)
        .order_by(Evidence.created_at.desc())
        .all()
    )

    # Filter to unextracted/updated primary evidences (avoid duplicating sibling child chunks unless large multi-chunk)
    pending_evidences = [
        ev
        for ev in all_evidences
        if (getattr(ev, "parent_evidence_id", None) is None or (getattr(ev, "chunk_index", 0) or 0) <= 1)
        and _needs_extraction(ev, source_map, force=force)
    ]

    counts = {
        "entities": 0,
        "relationships": 0,
        "decisions": 0,
        "tasks": 0,
        "risks": 0,
        "dependencies": 0,
        "gaps": 0,
        "batches_processed": 0,
        "records_processed": 0,
    }
    if not pending_evidences:
        return counts

    identity_map = build_project_identity_map(project_id, db)

    entity_map: Dict[str, KnowledgeEntity] = {
        e.name.strip().lower(): e
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == project_id).all()
    }
    existing_rel_keys = {
        (r.source_entity_id, r.target_entity_id, r.relation_type)
        for r in db.query(KnowledgeRelationship).filter(KnowledgeRelationship.project_id == project_id).all()
    }
    existing_decs = {
        d.title.strip().lower()
        for d in db.query(Decision).filter(Decision.project_id == project_id).all()
    }
    existing_tasks = {
        t.title.strip().lower()
        for t in db.query(TaskItem).filter(TaskItem.project_id == project_id).all()
    }
    existing_risks = {
        r.title.strip().lower()
        for r in db.query(RiskItem).filter(RiskItem.project_id == project_id).all()
    }
    existing_deps = {
        (d.source_component.lower(), d.target_component.lower())
        for d in db.query(Dependency).filter(Dependency.project_id == project_id).all()
    }
    existing_resps = {
        (r.owner.strip().lower(), r.domain.strip().lower())
        for r in db.query(Responsibility).filter(Responsibility.project_id == project_id).all()
    }
    existing_gaps = {
        g.title.strip().lower()
        for g in db.query(KnowledgeGap).filter(KnowledgeGap.project_id == project_id).all()
    }

    def _ensure_entity(
        name: str,
        entity_type: str,
        description: str,
        ev: Optional[Evidence] = None,
        owner_prop: Optional[str] = None,
    ) -> Optional[KnowledgeEntity]:
        clean_name = _s(name, 255)
        if not clean_name:
            return None
        if entity_type == "person":
            clean_name = resolve_author_name(clean_name, identity_map) or clean_name
            clean_name = _s(clean_name, 255)
        key = clean_name.lower()
        if key in entity_map:
            return entity_map[key]
        ke = KnowledgeEntity(
            project_id=project_id,
            created_by_user_id=actor_user_id,
            source_record_id=ev.source_record_id if ev else None,
            entity_type=_s(entity_type, 50, "component") or "component",
            name=clean_name,
            description=_s(description) or clean_name,
            properties={"owner": owner_prop} if owner_prop else {},
            confidence=0.78 if ev else 0.45,
            verification_status="Draft / AI Suggested",
            evidence_id=ev.id if ev else None,
        )
        db.add(ke)
        db.flush()
        entity_map[key] = ke
        counts["entities"] += 1
        return ke

    def _ensure_rel(
        src: Optional[KnowledgeEntity],
        dst: Optional[KnowledgeEntity],
        rel_type: str,
        context: str,
        ev: Optional[Evidence] = None,
    ) -> None:
        if not src or not dst or src.id == dst.id:
            return
        clean_rel = _s(rel_type, 50, "relates_to") or "relates_to"
        rkey = (src.id, dst.id, clean_rel)
        if rkey in existing_rel_keys:
            return
        db.add(
            KnowledgeRelationship(
                project_id=project_id,
                source_entity_id=src.id,
                target_entity_id=dst.id,
                relation_type=clean_rel,
                context=_s(context),
                confidence=0.78 if ev else 0.45,
                verification_status="Draft / AI Suggested",
                evidence_id=ev.id if ev else None,
                source_record_id=ev.source_record_id if ev else None,
            )
        )
        existing_rel_keys.add(rkey)
        counts["relationships"] += 1

    batch_size = max(1, min(int(max_records or 15), 25))
    max_batches = 8 if full_sweep else 1
    batches = [
        pending_evidences[i : i + batch_size]
        for i in range(0, min(len(pending_evidences), batch_size * max_batches), batch_size)
    ]

    now_utc = _utc_naive()
    now_iso = datetime.now(timezone.utc).isoformat()
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for batch in batches:
        records_payload: List[Dict[str, Any]] = []
        for ev in batch:
            raw_body = (getattr(ev, "full_text", None) or ev.excerpt or "").strip()
            resolved_author = resolve_author_name(ev.source_author, identity_map) or ev.source_author
            records_payload.append(
                {
                    "evidence_id": ev.id,
                    "source_record_id": ev.source_record_id,
                    "title": ev.source_title,
                    "source_type": ev.source_type,
                    "author": resolved_author,
                    "date": ev.source_timestamp.isoformat() if ev.source_timestamp else ev.created_at.isoformat(),
                    "content": raw_body[:2400],
                }
            )

        bundle = ai_engine.extract_knowledge_from_records(records_payload, project_name=project_name)
        counts["batches_processed"] += 1
        counts["records_processed"] += len(batch)

        def _ev_for(idx: int) -> Optional[Evidence]:
            if 1 <= idx <= len(batch):
                return batch[idx - 1]
            return batch[0] if batch else None

        # 1. Entities (with canonical person names)
        for item in bundle.entities:
            ev = _ev_for(item.evidence_index)
            owner_name = resolve_author_name(_s(item.owner, 255), identity_map) if item.owner else None
            _ensure_entity(
                name=item.name,
                entity_type=item.entity_type,
                description=item.description,
                ev=ev,
                owner_prop=owner_name,
            )

        # 2. Relationships
        for rel in bundle.relationships:
            ev = _ev_for(rel.evidence_index)
            src_name = resolve_author_name(_s(rel.source_name), identity_map) or _s(rel.source_name)
            dst_name = resolve_author_name(_s(rel.target_name), identity_map) or _s(rel.target_name)
            src = entity_map.get(src_name.strip().lower())
            dst = entity_map.get(dst_name.strip().lower())
            _ensure_rel(src, dst, rel.relation_type, _s(rel.context), ev=ev)

        # 3. Decisions + bidirectional graph sync
        for dec in bundle.decisions:
            dec_title = _s(dec.title, 500)
            if not dec_title or dec_title.lower() in existing_decs:
                continue
            ev = _ev_for(dec.evidence_index)
            maker = resolve_author_name(_s(dec.decision_maker, 255, "Contributor"), identity_map) or "Contributor"
            comp_name = _s(dec.component, 255) or None
            db.add(
                Decision(
                    project_id=project_id,
                    created_by_user_id=actor_user_id,
                    title=dec_title,
                    summary=_s(dec.summary) or dec_title,
                    reasoning=_s(dec.reasoning) or _s(dec.summary) or dec_title,
                    decision_maker=_s(maker, 255),
                    date=_s(dec.date, 50) or (ev.created_at.strftime("%Y-%m-%d") if ev else today_str),
                    component=comp_name,
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

            if comp_name and maker.lower() not in ("contributor", "unassigned", "unknown"):
                p_ent = _ensure_entity(maker, "person", f"Decision maker for {comp_name}", ev=ev)
                c_ent = _ensure_entity(comp_name, "component", _s(dec.summary) or dec_title, ev=ev)
                _ensure_rel(p_ent, c_ent, "decided", dec_title, ev=ev)

        # 4. Tasks
        for t in bundle.tasks:
            task_title = _s(t.title, 500)
            if not task_title or task_title.lower() in existing_tasks:
                continue
            ev = _ev_for(t.evidence_index)
            owner = resolve_author_name(_s(t.owner, 255, "Unassigned"), identity_map) or "Unassigned"
            raw_prio = _s(t.priority, 20).lower()
            raw_status = _s(t.status, 50).lower()
            db.add(
                TaskItem(
                    project_id=project_id,
                    created_by_user_id=actor_user_id,
                    title=task_title,
                    description=_s(t.description),
                    owner=_s(owner, 255),
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
        for r in bundle.risks:
            risk_title = _s(r.title, 500)
            if not risk_title or risk_title.lower() in existing_risks:
                continue
            ev = _ev_for(r.evidence_index)
            r_owner = resolve_author_name(_s(r.owner, 255), identity_map) if r.owner else None
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
                    owner=_s(r_owner, 255) if r_owner else None,
                    mitigation_strategy=_s(r.mitigation_strategy) or None,
                    related_components=[_s(str(c), 255) for c in (r.related_components or []) if _s(str(c))],
                    verification_status="Draft / AI Suggested",
                    evidence_ids=[ev.id] if ev else [],
                )
            )
            existing_risks.add(risk_title.lower())
            counts["risks"] += 1

        # 6. Dependencies + bidirectional graph sync
        for dep in bundle.dependencies:
            src_comp = _s(dep.source_component, 255)
            dst_comp = _s(dep.target_component, 255)
            pair = (src_comp.lower(), dst_comp.lower())
            if not pair[0] or not pair[1] or pair in existing_deps:
                continue
            ev = _ev_for(dep.evidence_index)
            d_owner = resolve_author_name(_s(dep.owner, 255), identity_map) if dep.owner else None
            raw_crit = _s(dep.criticality, 20, "high").lower() or "high"
            db.add(
                Dependency(
                    project_id=project_id,
                    source_component=src_comp,
                    target_component=dst_comp,
                    dependency_type=_s(dep.dependency_type, 50, "hard_blocker") or "hard_blocker",
                    description=_s(dep.description) or None,
                    owner=_s(d_owner, 255) if d_owner else None,
                    criticality=raw_crit,
                    verification_status="Draft / AI Suggested",
                    evidence_ids=[ev.id] if ev else [],
                )
            )
            existing_deps.add(pair)
            counts["dependencies"] += 1

            src_ent = _ensure_entity(src_comp, "component", _s(dep.description) or f"Component {src_comp}", ev=ev)
            dst_ent = _ensure_entity(dst_comp, "component", f"Dependency target {dst_comp}", ev=ev)
            _ensure_rel(src_ent, dst_ent, "depends_on", _s(dep.description) or dep.dependency_type or "dependency", ev=ev)

        # 7. Responsibilities + bidirectional graph sync
        for resp in bundle.responsibilities:
            ev = _ev_for(resp.evidence_index)
            r_owner = resolve_author_name(_s(resp.owner, 255), identity_map) or _s(resp.owner, 255)
            r_domain = _s(resp.domain, 255)
            if not r_owner or not r_domain:
                continue
            b_owner = resolve_author_name(_s(resp.backup_owner, 255), identity_map) if resp.backup_owner else None
            resp_key = (r_owner.strip().lower(), r_domain.strip().lower())
            if resp_key not in existing_resps:
                db.add(
                    Responsibility(
                        project_id=project_id,
                        owner=_s(r_owner, 255),
                        domain=r_domain,
                        scope=_s(resp.scope) or f"Ownership of {r_domain}",
                        criticality=_s(resp.criticality, 20, "high").lower() or "high",
                        backup_owner=_s(b_owner, 255) if b_owner else None,
                        verification_status="Draft / AI Suggested",
                        evidence_ids=[ev.id] if ev else [],
                    )
                )
                existing_resps.add(resp_key)

            owner_ent = _ensure_entity(r_owner, "person", f"Owner of {r_domain}", ev=ev)
            dom_ent = _ensure_entity(r_domain, "component", _s(resp.scope) or r_domain, ev=ev)
            _ensure_rel(owner_ent, dom_ent, "owns", _s(resp.scope) or f"Owns {r_domain}", ev=ev)
            if b_owner:
                b_ent = _ensure_entity(b_owner, "person", f"Backup owner for {r_domain}", ev=ev)
                _ensure_rel(b_ent, dom_ent, "backup_for", f"Backup owner for {r_domain}", ev=ev)

        # 8. Knowledge Gaps
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

        # Stamp watermarks on extracted records in this batch
        batch_stamp = _utc_naive()
        for ev in batch:
            meta = dict(ev.metadata_json or {})
            meta["extraction_processed_at"] = now_iso
            if ev.source_record_id and ev.source_record_id in source_map:
                sr = source_map[ev.source_record_id]
                sr.extraction_processed_at = batch_stamp
                if sr.sha256_hash:
                    meta["extracted_sha256"] = sr.sha256_hash
            ev.metadata_json = meta

    # Consolidate duplicate person nodes via cross-platform identity stitching
    merged_people = merge_duplicate_person_entities(db, project_id, identity_map=identity_map)
    if merged_people:
        counts["merged_people"] = merged_people

    record_activity(
        db=db,
        action="knowledge.extracted",
        entity_type="project",
        entity_id=project_id,
        user_id=actor_user_id,
        project_id=project_id,
        details={"message": "AI incrementally extracted structured project knowledge", "counts": counts},
    )
    db.commit()
    return counts
