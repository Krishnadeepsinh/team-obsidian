import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Integer, JSON, Index
from sqlalchemy.orm import relationship
from app.core.database import Base

VERIFICATION_STATUSES = [
    "Draft / AI Suggested",
    "Supported by Evidence",
    "Needs Human Verification",
    "Verified by Reviewer",
    "Contradicted",
    "Outdated",
    "Unknown / Missing Evidence",
]


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


class Evidence(Base):
    __tablename__ = "evidences"
    __table_args__ = (
        Index("idx_evidence_project_status", "project_id", "verification_status"),
        Index("idx_evidence_project_parent", "project_id", "parent_evidence_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_record_id = Column(String(36), ForeignKey("source_records.id", ondelete="SET NULL"), nullable=True, index=True)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    chunk_id = Column(String(36), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True, index=True)
    parent_evidence_id = Column(String(36), ForeignKey("evidences.id", ondelete="SET NULL"), nullable=True, index=True)
    chunk_index = Column(Integer, default=0)
    total_chunks = Column(Integer, default=1)
    source_type = Column(String(50), nullable=False)
    source_id = Column(String(255), nullable=False)
    source_title = Column(String(500), nullable=False)
    source_url = Column(String(1000), nullable=True)
    source_author = Column(String(255), nullable=True)
    source_timestamp = Column(DateTime, nullable=True)
    claim_type = Column(String(50), default="source_excerpt")
    excerpt = Column(Text, nullable=False)
    full_text = Column(Text, nullable=True)
    ai_interpretation = Column(Text, nullable=False)
    confidence = Column(Float, default=0.0)
    verification_status = Column(String(50), default="Needs Human Verification")
    content_hash = Column(String(64), nullable=False)
    metadata_json = Column(JSON, default=dict)
    reviewer_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    source_record = relationship("SourceRecord", back_populates="evidences")
    reviews = relationship("EvidenceReview", back_populates="evidence", cascade="all, delete-orphan")


class EvidenceReview(Base):
    __tablename__ = "evidence_reviews"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    evidence_id = Column(String(36), ForeignKey("evidences.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewer_name = Column(String(255), nullable=True)
    action = Column(String(50), nullable=False)
    previous_status = Column(String(50), nullable=False)
    new_status = Column(String(50), nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    evidence = relationship("Evidence", back_populates="reviews")
