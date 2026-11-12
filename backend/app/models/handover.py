import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Boolean, Integer, JSON
from sqlalchemy.orm import relationship
from app.core.database import Base

HANDOVER_STATES = [
    "draft",
    "processing",
    "needs_review",
    "changes_requested",
    "in_review",
    "approved",
    "acknowledged",
    "published",
    "archived",
]


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


class Handover(Base):
    __tablename__ = "handovers"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    created_by_user_id = Column(String(36), nullable=True)
    title = Column(String(255), nullable=False)
    departing_employee_name = Column(String(255), nullable=False)
    departing_employee_role = Column(String(255), nullable=False)
    incoming_employee_name = Column(String(255), nullable=False)
    incoming_employee_role = Column(String(255), nullable=False)
    status = Column(String(50), default="needs_review")
    target_date = Column(String(50), nullable=True)
    selected_sources = Column(JSON, default=list)
    selected_categories = Column(JSON, default=list)
    reconstruction_stats = Column(JSON, default=dict)
    overall_confidence = Column(Float, default=0.0)
    confidence_breakdown = Column(JSON, default=dict)
    pdf_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="handovers")
    sections = relationship(
        "HandoverSection",
        back_populates="handover",
        cascade="all, delete-orphan",
        order_by="HandoverSection.section_number",
    )
    claims = relationship("HandoverClaim", back_populates="handover", cascade="all, delete-orphan")
    approvals = relationship(
        "HandoverApproval",
        back_populates="handover",
        cascade="all, delete-orphan",
        order_by="HandoverApproval.order_index",
    )
    versions = relationship(
        "HandoverVersion",
        back_populates="handover",
        cascade="all, delete-orphan",
        order_by="HandoverVersion.version_number.desc()",
    )


class HandoverSection(Base):
    __tablename__ = "handover_sections"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    handover_id = Column(String(36), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    section_number = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    is_verified = Column(Boolean, default=False)
    verification_status = Column(String(50), default="Needs Human Verification")
    confidence = Column(Float, default=0.0)
    evidence_ids = Column(JSON, default=list)
    comments = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    handover = relationship("Handover", back_populates="sections")
    claims = relationship("HandoverClaim", back_populates="section", cascade="all, delete-orphan")


class HandoverClaim(Base):
    __tablename__ = "handover_claims"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    handover_id = Column(String(36), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    section_id = Column(String(36), ForeignKey("handover_sections.id", ondelete="CASCADE"), nullable=False, index=True)
    claim_text = Column(Text, nullable=False)
    verification_status = Column(String(50), default="Draft / AI Suggested")
    confidence = Column(Float, default=0.0)
    evidence_ids = Column(JSON, default=list)
    reviewer_id = Column(String(36), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    handover = relationship("Handover", back_populates="claims")
    section = relationship("HandoverSection", back_populates="claims")


class HandoverApproval(Base):
    __tablename__ = "handover_approvals"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    handover_id = Column(String(36), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    approver_user_id = Column(String(36), nullable=True)
    approver_name = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False)
    status = Column(String(50), default="pending")
    is_required = Column(Boolean, default=True)
    order_index = Column(Integer, default=0)
    notes = Column(Text, nullable=True)
    signed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    handover = relationship("Handover", back_populates="approvals")


class HandoverVersion(Base):
    __tablename__ = "handover_versions"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    handover_id = Column(String(36), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    version_number = Column(Integer, nullable=False)
    user_id = Column(String(36), nullable=True)
    changed_section = Column(String(255), nullable=True)
    previous_content = Column(Text, nullable=True)
    new_content = Column(Text, nullable=True)
    reason = Column(Text, nullable=True)
    changelog = Column(Text, nullable=True)
    snapshot = Column(JSON, nullable=False)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    handover = relationship("Handover", back_populates="versions")


class ReadinessSimulation(Base):
    __tablename__ = "readiness_simulations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    handover_id = Column(String(36), ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    candidate_name = Column(String(255), nullable=False)
    overall_score = Column(Float, nullable=False, default=0.0)
    passed = Column(Boolean, nullable=False, default=False)
    scenarios_json = Column(JSON, default=list)
    responses_json = Column(JSON, default=list)
    summary_feedback = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)

    handover = relationship("Handover")
