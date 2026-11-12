import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Text,
    DateTime,
    Float,
    ForeignKey,
    Boolean,
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


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=False)
    tier = Column(String(50), default="enterprise")
    owner_id = Column(String(36), nullable=True, index=True)
    is_personal = Column(Boolean, default=False)
    settings = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    workspaces = relationship("Workspace", back_populates="organization", cascade="all, delete-orphan")
    users = relationship("User", back_populates="organization")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    owner_id = Column(String(36), nullable=True, index=True)
    is_personal = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    organization = relationship("Organization", back_populates="workspaces")
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    personal_workspace_id = Column(String(36), nullable=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    name = Column(String(255), nullable=False)
    role = Column(String(50), default="developer")
    title = Column(String(255), nullable=True)
    department = Column(String(100), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    password_hash = Column(String(255), nullable=False)
    password_updated_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)

    organization = relationship("Organization", back_populates="users")
    memberships = relationship("ProjectMember", back_populates="user", cascade="all, delete-orphan")
    reset_tokens = relationship("PasswordResetToken", back_populates="user", cascade="all, delete-orphan")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)

    user = relationship("User", back_populates="reset_tokens")


class Project(Base):
    __tablename__ = "projects"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    workspace_id = Column(String(36), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(String(36), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="active")
    priority = Column(String(20), default="medium")
    tags = Column(JSON, default=list)
    is_demo = Column(Boolean, default=False)
    target_handover_date = Column(String(50), nullable=True)
    departing_user_id = Column(String(36), nullable=True)
    incoming_user_id = Column(String(36), nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    workspace = relationship("Workspace", back_populates="projects")
    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="project", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="project", cascade="all, delete-orphan")
    handovers = relationship("Handover", back_populates="project", cascade="all, delete-orphan")


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_role = Column(String(50), default="developer")
    status = Column(String(50), default="active")
    joined_at = Column(DateTime, default=utc_now)

    project = relationship("Project", back_populates="members")
    user = relationship("User", back_populates="memberships")


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    __table_args__ = (
        Index("idx_activity_project_created", "project_id", "created_at"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    org_id = Column(String(36), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actor_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(String(36), nullable=False)
    details = Column(JSON, default=dict)
    ip_address = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=utc_now, index=True)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True)
    title = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    type = Column(String(50), default="info")
    link = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utc_now)


class RevokedToken(Base):
    """Persisted JWT JTI revocation store surviving worker restarts and multi-worker scaling."""

    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True)
    expires_ts = Column(Float, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)


class RateLimitEvent(Base):
    """Persisted sliding-window rate-limit counter surviving worker restarts."""

    __tablename__ = "rate_limit_events"
    __table_args__ = (
        Index("idx_ratelimit_bucket_ts", "bucket_key", "created_ts"),
    )

    id = Column(String(36), primary_key=True, default=generate_uuid)
    bucket_key = Column(String(255), nullable=False, index=True)
    created_ts = Column(Float, nullable=False, index=True)

