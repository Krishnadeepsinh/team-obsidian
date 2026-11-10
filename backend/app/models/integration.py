import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    ForeignKey,
    Boolean,
    Integer,
    JSON,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from app.core.database import Base


def utc_now():
    return datetime.now(timezone.utc)


def generate_uuid():
    return str(uuid.uuid4())


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    is_org_level = Column(Boolean, default=False)
    provider = Column(String(50), nullable=False)  # github, slack, notion, gdrive, manual
    name = Column(String(255), nullable=False)
    status = Column(String(50), default="connected")  # connected, disconnected, syncing, error
    auth_type = Column(String(50), default="oauth")  # oauth, api_token, webhook
    auth_status = Column(String(50), default="unverified")  # verified, unverified, error, revoked
    connected_account = Column(String(255), nullable=True)
    scopes = Column(JSON, default=list)
    credentials = Column(JSON, default=dict)  # Fernet-encrypted credentials payload
    config = Column(JSON, default=dict)  # repos, channels, page targets
    sync_cursor = Column(JSON, default=dict)  # incremental sync timestamps/cursors per target
    last_sync = Column(DateTime, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    items_synced = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="integrations")
    source_records = relationship("SourceRecord", back_populates="integration", cascade="all, delete-orphan")
    events = relationship("SourceEvent", back_populates="integration", cascade="all, delete-orphan")


class SourceRecord(Base):
    __tablename__ = "source_records"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", "external_id", name="uq_source_record_project_ext"),
        Index("idx_source_record_project_type", "project_id", "source_type"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    integration_id = Column(String(36), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_type = Column(String(50), nullable=False)
    external_id = Column(String(255), nullable=False)
    title = Column(String(500), nullable=False)
    author = Column(String(255), nullable=True)
    url = Column(String(1000), nullable=True)
    content = Column(Text, nullable=False)
    raw_payload = Column(JSON, default=dict)
    metadata_json = Column(JSON, default=dict)
    sha256_hash = Column(String(64), nullable=False)
    source_timestamp = Column(DateTime, nullable=True)
    ingested_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    integration = relationship("Integration", back_populates="source_records")
    evidences = relationship("Evidence", back_populates="source_record", cascade="all, delete-orphan")


class SourceEvent(Base):
    __tablename__ = "source_events"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    integration_id = Column(String(36), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False)
    status = Column(String(50), default="success")
    records_added = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_skipped = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    details = Column(JSON, default=dict)
    timestamp = Column(DateTime, default=utc_now, index=True)

    integration = relationship("Integration", back_populates="events")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    mime_type = Column(String(120), nullable=True)
    file_size_bytes = Column(Integer, default=0)
    storage_path = Column(String(500), nullable=True)
    sha256_hash = Column(String(64), nullable=False, index=True)
    status = Column(String(50), default="processed")
    extracted_text = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0)
    page_count = Column(Integer, nullable=True)
    sheet_names = Column(JSON, default=list)
    metadata_json = Column(JSON, default=dict)
    uploaded_by = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("idx_doc_chunk_project_doc", "project_id", "document_id"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    document_id = Column(String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    page_number = Column(Integer, nullable=True)
    sheet_name = Column(String(255), nullable=True)
    heading = Column(String(500), nullable=True)
    paragraph_ref = Column(String(255), nullable=True)
    start_char = Column(Integer, nullable=False, default=0)
    end_char = Column(Integer, nullable=False, default=0)
    content = Column(Text, nullable=False)
    sha256_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, default=utc_now)

    document = relationship("Document", back_populates="chunks")
