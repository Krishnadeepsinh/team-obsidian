import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Boolean, JSON, Index
from pgvector.sqlalchemy import Vector
from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"
    __table_args__ = (
        Index("idx_ke_project_type", "project_id", "entity_type"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), nullable=True)
    source_record_id = Column(String(36), ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    entity_type = Column(String(50), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    properties = Column(JSON, default=dict)
    confidence = Column(Float, default=0.0)
    verification_status = Column(String(50), default="Needs Human Verification")
    evidence_id = Column(String(36), ForeignKey("evidences.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class KnowledgeRelationship(Base):
    __tablename__ = "knowledge_relationships"
    __table_args__ = (
        Index("idx_kr_project_src_dst", "project_id", "source_entity_id", "target_entity_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_entity_id = Column(String(36), ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_entity_id = Column(String(36), ForeignKey("knowledge_entities.id", ondelete="CASCADE"), nullable=False, index=True)
    relation_type = Column(String(50), nullable=False)
    context = Column(Text, nullable=True)
    confidence = Column(Float, default=0.0)
    verification_status = Column(String(50), default="Needs Human Verification")
    evidence_id = Column(String(36), ForeignKey("evidences.id", ondelete="SET NULL"), nullable=True)
    source_record_id = Column(String(36), ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=utc_now)


class Decision(Base):
    __tablename__ = "decisions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), nullable=True)
    title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    reasoning = Column(Text, nullable=False)
    decision_maker = Column(String(255), nullable=False)
    date = Column(String(50), nullable=False)
    component = Column(String(255), nullable=True)
    decision_type = Column(String(50), default="technical")
    status = Column(String(50), default="accepted")
    verification_status = Column(String(50), default="Needs Human Verification")
    alternatives = Column(JSON, default=list)
    tradeoffs = Column(JSON, default=list)
    consequences = Column(JSON, default=list)
    affected_components = Column(JSON, default=list)
    risks = Column(JSON, default=list)
    supersedes = Column(JSON, default=list)
    superseded_by = Column(String(36), nullable=True)
    confidence = Column(Float, default=0.0)
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class TaskItem(Base):
    __tablename__ = "task_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    owner = Column(String(255), nullable=False)
    component = Column(String(255), nullable=True)
    priority = Column(String(20), default="medium")
    status = Column(String(50), default="open")
    verification_status = Column(String(50), default="Needs Human Verification")
    deadline = Column(String(50), nullable=True)
    dependencies = Column(JSON, default=list)
    is_departing_owner = Column(Boolean, default=False)
    suggested_reassignment = Column(String(255), nullable=True)
    confidence = Column(Float, default=0.0)
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class Dependency(Base):
    __tablename__ = "dependencies"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_component = Column(String(255), nullable=False)
    target_component = Column(String(255), nullable=False)
    dependency_type = Column(String(50), default="hard_blocker")
    description = Column(Text, nullable=True)
    owner = Column(String(255), nullable=True)
    criticality = Column(String(20), default="high")
    verification_status = Column(String(50), default="Needs Human Verification")
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class Responsibility(Base):
    __tablename__ = "responsibilities"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    owner = Column(String(255), nullable=False)
    domain = Column(String(255), nullable=False)
    scope = Column(Text, nullable=False)
    criticality = Column(String(20), default="high")
    backup_owner = Column(String(255), nullable=True)
    verification_status = Column(String(50), default="Needs Human Verification")
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class RiskItem(Base):
    __tablename__ = "risk_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), nullable=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    category = Column(String(50), default="technical_risk")
    severity = Column(String(20), default="high")
    likelihood = Column(String(20), default="medium")
    impact = Column(Text, nullable=True)
    owner = Column(String(255), nullable=True)
    mitigation_strategy = Column(Text, nullable=True)
    status = Column(String(50), default="open")
    verification_status = Column(String(50), default="Needs Human Verification")
    related_components = Column(JSON, default=list)
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class KnowledgeGap(Base):
    __tablename__ = "knowledge_gaps"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=False)
    gap_type = Column(String(50), nullable=False)
    severity = Column(String(20), default="high")
    priority = Column(String(20), default="high")
    impact = Column(Text, nullable=False)
    business_impact = Column(Text, nullable=True)
    technical_impact = Column(Text, nullable=True)
    recommended_action = Column(Text, nullable=False)
    assigned_reviewer = Column(String(255), nullable=True)
    status = Column(String(50), default="identified")
    evidence_ids = Column(JSON, default=list)
    created_at = Column(DateTime, default=utc_now)


class EmbeddingRecord(Base):
    __tablename__ = "embedding_records"
    __table_args__ = (
        Index("idx_embedding_project_entity", "project_id", "entity_type", "entity_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    text_content = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=False)
    embedding_vector = Column(Vector(384).with_variant(JSON(), "sqlite"), nullable=True)
    created_at = Column(DateTime, default=utc_now)


class KnowledgeDriftEvent(Base):
    __tablename__ = "knowledge_drift_events"
    __table_args__ = (
        Index("idx_drift_project_status", "project_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_id = Column(String(36), nullable=True)
    source_record_id = Column(String(36), nullable=True)
    drift_type = Column(String(50), nullable=False, default="contradiction")  # contradiction, superseded, ownership_change, dependency_shift, doc_stale
    severity = Column(String(20), nullable=False, default="high")  # critical, high, medium, low
    target_entity_type = Column(String(50), nullable=False, default="decision")  # decision, risk, dependency, handover_claim, evidence
    target_entity_id = Column(String(36), nullable=False)
    target_title = Column(String(500), nullable=False)
    summary = Column(Text, nullable=False)
    evidence_excerpt = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="open")  # open, acknowledged, resolved, dismissed
    resolved_by_user_id = Column(String(36), nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now, index=True)
