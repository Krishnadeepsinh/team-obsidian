import sys
sys.path.insert(0, "backend")
from app.core.database import SessionLocal
from app.models.workspace import Project, User, Organization, Workspace, ProjectMember
from app.models.handover import Handover, HandoverSection, HandoverApproval, HandoverVersion
from app.models.integration import Integration, SourceRecord, Document
from app.models.knowledge import Decision, TaskItem, RiskItem, KnowledgeEntity, KnowledgeGap, Dependency, Responsibility
from app.models.evidence import Evidence

db = SessionLocal()
print("Total Projects:", db.query(Project).count())
print("Total Users:", db.query(User).count())
print("Total Organizations:", db.query(Organization).count())
print("Total Workspaces:", db.query(Workspace).count())
print("Total Decisions:", db.query(Decision).count())
print("Total Tasks:", db.query(TaskItem).count())
print("Total Evidences:", db.query(Evidence).count())
print("Total Handovers:", db.query(Handover).count())

print("\n--- All Projects ---")
for p in db.query(Project).all():
    print(f"Project ID: {p.id} | Name: {p.name} | Creator: {p.creator_id}")

print("\n--- All Users ---")
for u in db.query(User).all():
    print(f"User ID: {u.id} | Email: {u.email} | Name: {u.name}")
db.close()
