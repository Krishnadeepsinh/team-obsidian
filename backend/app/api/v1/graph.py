from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeEntity, KnowledgeRelationship
from app.models.workspace import User
from app.services.audit_service import record_activity
from app.services.graph_service import graph_service
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


class BackupOwnerAssignRequest(BaseModel):
    component_id: str = Field(..., min_length=1, max_length=64)
    backup_person_name: str = Field(..., min_length=1, max_length=120)
    relation_type: str = Field(default="maintains", max_length=32)


@router.post("/extract/{project_id}")
def trigger_graph_extraction(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Run AI knowledge extraction to build/refresh entities, relationships, decisions, risks, and gaps."""
    verify_project_access(project_id, current_user, db, require_write=True)
    counts = extract_and_persist_project_knowledge(db, project_id, actor_user_id=current_user.id)
    return {"status": "success", "project_id": project_id, "extracted": counts}


@router.get("/react-flow")
def get_react_flow_graph(
    project_id: Optional[str] = None,
    entity_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    layout: str = Query("vertical"),
    hide_isolated: bool = Query(False),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    e_query = db.query(KnowledgeEntity)
    r_query = db.query(KnowledgeRelationship)

    if project_id:
        verify_project_access(project_id, current_user, db)
        e_query = e_query.filter(KnowledgeEntity.project_id == project_id)
        r_query = r_query.filter(KnowledgeRelationship.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return graph_service.to_react_flow([], [], layout=layout, hide_isolated=hide_isolated)
        e_query = e_query.filter(KnowledgeEntity.project_id.in_(p_ids))
        r_query = r_query.filter(KnowledgeRelationship.project_id.in_(p_ids))

    raw_entities = e_query.all()
    if entity_type and entity_type.lower() != "all":
        raw_entities = [e for e in raw_entities if (e.entity_type or "").lower() == entity_type.lower()]
    if search:
        s = search.lower()
        raw_entities = [
            e for e in raw_entities if s in (e.name or "").lower() or s in (e.description or "").lower()
        ]

    allowed_ids = {e.id for e in raw_entities}
    entities = [
        {
            "id": e.id,
            "name": e.name,
            "entity_type": e.entity_type,
            "description": e.description,
            "confidence": e.confidence,
            "verification_status": getattr(e, "verification_status", "Needs Human Verification"),
            "evidence_id": e.evidence_id,
            "properties": e.properties or {},
        }
        for e in raw_entities
    ]

    relationships = [
        {
            "id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "context": r.context,
            "confidence": r.confidence,
        }
        for r in r_query.all()
        if r.source_entity_id in allowed_ids and r.target_entity_id in allowed_ids
    ]

    return graph_service.to_react_flow(entities, relationships, layout=layout, hide_isolated=hide_isolated)


@router.get("/blast-radius/{node_id}")
def get_node_blast_radius(
    node_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_node = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == node_id).first()
    if not target_node:
        raise HTTPException(status_code=404, detail="Entity node not found")

    verify_project_access(target_node.project_id, current_user, db)

    entities = [
        {"id": e.id, "name": e.name, "entity_type": e.entity_type, "description": e.description}
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == target_node.project_id).all()
    ]
    relationships = [
        {
            "id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "context": r.context,
        }
        for r in db.query(KnowledgeRelationship)
        .filter(KnowledgeRelationship.project_id == target_node.project_id)
        .all()
    ]

    G = graph_service.build_graph(entities, relationships)
    affected_ids = graph_service.calculate_blast_radius(G, node_id)
    upstream_ids = graph_service.calculate_upstream_dependencies(G, node_id)

    affected_nodes = [e for e in entities if e["id"] in affected_ids]
    upstream_nodes = [e for e in entities if e["id"] in upstream_ids]
    spof_warnings = graph_service.detect_single_points_of_failure(entities, relationships)

    return {
        "node_id": node_id,
        "node_name": target_node.name,
        "node_type": target_node.entity_type,
        "affected_count": len(affected_nodes),
        "affected_entities": affected_nodes,
        "upstream_count": len(upstream_nodes),
        "upstream_entities": upstream_nodes,
        "spof_warnings": spof_warnings,
    }


@router.get("/departure-impact/{person_node_id}")
def get_departure_impact(
    person_node_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Simulate bus-factor & orphaned downstream blast radius if a given person node leaves."""
    person_node = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == person_node_id).first()
    if not person_node:
        raise HTTPException(status_code=404, detail="Person entity not found.")
    verify_project_access(person_node.project_id, current_user, db)

    entities = [
        {"id": e.id, "name": e.name, "entity_type": e.entity_type, "description": e.description}
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == person_node.project_id).all()
    ]
    relationships = [
        {
            "id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
            "context": r.context,
        }
        for r in db.query(KnowledgeRelationship)
        .filter(KnowledgeRelationship.project_id == person_node.project_id)
        .all()
    ]
    return graph_service.simulate_person_departure(entities, relationships, person_node_id)


@router.post("/assign-backup-owner")
def assign_backup_owner(
    req: BackupOwnerAssignRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Assign a backup owner/maintainer to a Knowledge Graph component to eliminate a Single Point of Failure."""
    component = db.query(KnowledgeEntity).filter(KnowledgeEntity.id == req.component_id).first()
    if not component:
        raise HTTPException(status_code=404, detail="Target component node not found.")
    verify_project_access(component.project_id, current_user, db, require_write=True)

    rel_type = req.relation_type.strip().lower()
    if rel_type not in {"owns", "maintains"}:
        raise HTTPException(status_code=400, detail="relation_type must be 'owns' or 'maintains'.")

    backup_name = req.backup_person_name.strip()
    if not backup_name:
        raise HTTPException(status_code=400, detail="backup_person_name cannot be empty.")

    project_people = (
        db.query(KnowledgeEntity)
        .filter(
            KnowledgeEntity.project_id == component.project_id,
            KnowledgeEntity.entity_type == "person",
        )
        .all()
    )
    backup_person = next(
        (p for p in project_people if (p.name or "").strip().lower() == backup_name.lower()),
        None,
    )
    if not backup_person:
        backup_person = KnowledgeEntity(
            project_id=component.project_id,
            created_by_user_id=current_user.id,
            entity_type="person",
            name=backup_name,
            description="Backup owner assigned for SPOF resilience",
            confidence=0.95,
            verification_status="Verified by Reviewer",
        )
        db.add(backup_person)
        db.flush()

    if backup_person.id == component.id:
        raise HTTPException(status_code=400, detail="Cannot assign a node as its own backup owner.")

    existing_rel = (
        db.query(KnowledgeRelationship)
        .filter(
            KnowledgeRelationship.project_id == component.project_id,
            KnowledgeRelationship.source_entity_id == backup_person.id,
            KnowledgeRelationship.target_entity_id == component.id,
            KnowledgeRelationship.relation_type == rel_type,
        )
        .first()
    )
    if not existing_rel:
        existing_rel = KnowledgeRelationship(
            project_id=component.project_id,
            source_entity_id=backup_person.id,
            target_entity_id=component.id,
            relation_type=rel_type,
            context=f"Assigned as backup owner for {component.name} by {current_user.email}",
            confidence=0.95,
            verification_status="Verified by Reviewer",
        )
        db.add(existing_rel)

    record_activity(
        db=db,
        action="graph.backup_owner_assigned",
        entity_type="knowledge_entity",
        entity_id=component.id,
        user_id=current_user.id,
        project_id=component.project_id,
        actor_email=current_user.email,
        details={"message": f"Assigned backup owner '{backup_name}' ({rel_type}) to '{component.name}'"},
    )
    db.commit()

    # Recompute SPOF list after mitigation
    entities = [
        {"id": e.id, "name": e.name, "entity_type": e.entity_type, "description": e.description}
        for e in db.query(KnowledgeEntity).filter(KnowledgeEntity.project_id == component.project_id).all()
    ]
    relationships = [
        {
            "id": r.id,
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
        }
        for r in db.query(KnowledgeRelationship)
        .filter(KnowledgeRelationship.project_id == component.project_id)
        .all()
    ]
    remaining_spofs = graph_service.detect_single_points_of_failure(entities, relationships)
    still_spof = any(s["component_id"] == component.id for s in remaining_spofs)

    return {
        "status": "success",
        "component_id": component.id,
        "component_name": component.name,
        "backup_person_id": backup_person.id,
        "backup_person_name": backup_person.name,
        "relationship_id": existing_rel.id,
        "is_still_spof": still_spof,
        "remaining_spof_count": len(remaining_spofs),
    }


@router.get("/export/mermaid")
def export_graph_mermaid(
    project_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export authorized project Knowledge Graph as a Mermaid flowchart diagram."""
    e_query = db.query(KnowledgeEntity)
    r_query = db.query(KnowledgeRelationship)
    if project_id:
        verify_project_access(project_id, current_user, db)
        e_query = e_query.filter(KnowledgeEntity.project_id == project_id)
        r_query = r_query.filter(KnowledgeRelationship.project_id == project_id)
    else:
        p_ids = get_user_accessible_project_ids(current_user, db)
        if not p_ids:
            return {"mermaid": "flowchart TD\n", "node_count": 0, "edge_count": 0}
        e_query = e_query.filter(KnowledgeEntity.project_id.in_(p_ids))
        r_query = r_query.filter(KnowledgeRelationship.project_id.in_(p_ids))

    entities = [
        {"id": e.id, "name": e.name, "entity_type": e.entity_type}
        for e in e_query.all()
    ]
    allowed_ids = {e["id"] for e in entities}
    relationships = [
        {
            "source_entity_id": r.source_entity_id,
            "target_entity_id": r.target_entity_id,
            "relation_type": r.relation_type,
        }
        for r in r_query.all()
        if r.source_entity_id in allowed_ids and r.target_entity_id in allowed_ids
    ]
    return {
        "mermaid": graph_service.to_mermaid(entities, relationships),
        "node_count": len(entities),
        "edge_count": len(relationships),
    }
