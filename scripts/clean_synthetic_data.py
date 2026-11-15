import os
import sys

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.core.database import SessionLocal
from app.models.evidence import Evidence
from app.models.handover import Handover, HandoverApproval, HandoverSection, HandoverVersion, HandoverClaim
from app.models.integration import Document, DocumentChunk, Integration, SourceEvent, SourceRecord
from app.models.knowledge import (
    Decision,
    Dependency,
    EmbeddingRecord,
    KnowledgeEntity,
    KnowledgeGap,
    KnowledgeRelationship,
    Responsibility,
    RiskItem,
    TaskItem,
)
from app.models.workspace import ActivityLog, Organization, Project, ProjectMember, Workspace


def purge_demo_projects_only():
    """Safely remove only explicit synthetic demo projects (is_demo == True), never touching real customer data."""
    if os.getenv("CONFIRM_DEMO_PURGE") != "YES":
        raise SystemExit("Refusing to purge: set CONFIRM_DEMO_PURGE=YES to delete is_demo=True synthetic sandbox projects.")

    db = SessionLocal()
    try:
        demo_projects = db.query(Project).filter(Project.is_demo == True).all()  # noqa: E712
        demo_p_ids = [p.id for p in demo_projects]
        if not demo_p_ids:
            print("No synthetic demo projects found. Real customer workspaces untouched.")
            return

        h_ids = [h.id for h in db.query(Handover).filter(Handover.project_id.in_(demo_p_ids)).all()]
        if h_ids:
            db.query(HandoverClaim).filter(HandoverClaim.handover_id.in_(h_ids)).delete(synchronize_session=False)
            db.query(HandoverVersion).filter(HandoverVersion.handover_id.in_(h_ids)).delete(synchronize_session=False)
            db.query(HandoverApproval).filter(HandoverApproval.handover_id.in_(h_ids)).delete(synchronize_session=False)
            db.query(HandoverSection).filter(HandoverSection.handover_id.in_(h_ids)).delete(synchronize_session=False)
            db.query(Handover).filter(Handover.id.in_(h_ids)).delete(synchronize_session=False)

        for model in (
            EmbeddingRecord, KnowledgeRelationship, KnowledgeEntity, Dependency,
            Responsibility, KnowledgeGap, RiskItem, TaskItem, Decision, Evidence,
            DocumentChunk, Document, SourceRecord, ProjectMember, ActivityLog,
        ):
            db.query(model).filter(model.project_id.in_(demo_p_ids)).delete(synchronize_session=False)

        i_ids = [i.id for i in db.query(Integration).filter(Integration.project_id.in_(demo_p_ids)).all()]
        if i_ids:
            db.query(SourceEvent).filter(SourceEvent.integration_id.in_(i_ids)).delete(synchronize_session=False)
            db.query(Integration).filter(Integration.id.in_(i_ids)).delete(synchronize_session=False)

        db.query(Project).filter(Project.id.in_(demo_p_ids)).delete(synchronize_session=False)
        db.commit()
        print(f"Purged {len(demo_p_ids)} synthetic demo project(s). All real customer records preserved.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    purge_demo_projects_only()
