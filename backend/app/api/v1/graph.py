from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.permissions import get_user_accessible_project_ids, verify_project_access
from app.core.security import get_current_user
from app.models.knowledge import KnowledgeEntity, KnowledgeRelationship
from app.models.workspace import User
from app.services.graph_service import graph_service
from app.services.knowledge_extractor import extract_and_persist_project_knowledge

router = APIRouter(prefix="/graph", tags=["Knowledge Graph"])


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
            return graph_service.to_react_flow([], [])
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

    return graph_service.to_react_flow(entities, relationships)


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
