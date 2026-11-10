"""Phase 1 & 2 security, data foundation, and pgvector migration

Revision ID: 001_phase1_phase2
Revises: None
Create Date: 2026-11-10
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001_phase1_phase2"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, col: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(c["name"] == col for c in insp.get_columns(table))


def _add_col_if_missing(insp, table: str, col: sa.Column) -> None:
    if _has_table(insp, table) and not _has_column(insp, table, col.name):
        op.add_column(table, col)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        op.execute('CREATE EXTENSION IF NOT EXISTS "vector"')
        op.execute('CREATE EXTENSION IF NOT EXISTS "pg_trgm"')

    # Ensure core base tables exist on fresh DBs before incremental additions
    from app.core.database import Base
    import app.models  # noqa: F401
    Base.metadata.create_all(bind=bind)
    insp = sa.inspect(bind)

    # 1. Organizations
    _add_col_if_missing(insp, "organizations", sa.Column("settings", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "organizations", sa.Column("updated_at", sa.DateTime(), nullable=True))

    # 2. Workspaces
    _add_col_if_missing(insp, "workspaces", sa.Column("updated_at", sa.DateTime(), nullable=True))

    # 3. Users
    _add_col_if_missing(insp, "users", sa.Column("password_updated_at", sa.DateTime(), nullable=True))
    _add_col_if_missing(insp, "users", sa.Column("last_login_at", sa.DateTime(), nullable=True))

    # 4. Projects
    _add_col_if_missing(insp, "projects", sa.Column("is_demo", sa.Boolean(), server_default=sa.text("false"), nullable=True))
    _add_col_if_missing(insp, "projects", sa.Column("target_handover_date", sa.String(50), nullable=True))
    _add_col_if_missing(insp, "projects", sa.Column("departing_user_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "projects", sa.Column("incoming_user_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "projects", sa.Column("metadata_json", sa.JSON(), nullable=True))

    # 5. ActivityLog & Notification
    _add_col_if_missing(insp, "activity_logs", sa.Column("org_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "activity_logs", sa.Column("actor_email", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "notifications", sa.Column("project_id", sa.String(36), nullable=True))

    # 6. Integration, SourceRecord, SourceEvent, Document
    _add_col_if_missing(insp, "integrations", sa.Column("auth_status", sa.String(50), server_default="unverified", nullable=True))
    _add_col_if_missing(insp, "integrations", sa.Column("connected_account", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "integrations", sa.Column("scopes", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "integrations", sa.Column("sync_cursor", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "integrations", sa.Column("last_error_at", sa.DateTime(), nullable=True))

    _add_col_if_missing(insp, "source_records", sa.Column("metadata_json", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "source_records", sa.Column("source_timestamp", sa.DateTime(), nullable=True))
    _add_col_if_missing(insp, "source_records", sa.Column("updated_at", sa.DateTime(), nullable=True))

    _add_col_if_missing(insp, "source_events", sa.Column("records_skipped", sa.Integer(), server_default="0", nullable=True))
    _add_col_if_missing(insp, "source_events", sa.Column("error_message", sa.Text(), nullable=True))

    _add_col_if_missing(insp, "documents", sa.Column("mime_type", sa.String(120), nullable=True))
    _add_col_if_missing(insp, "documents", sa.Column("page_count", sa.Integer(), nullable=True))
    _add_col_if_missing(insp, "documents", sa.Column("sheet_names", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "documents", sa.Column("metadata_json", sa.JSON(), nullable=True))

    # 7. Evidences
    _add_col_if_missing(insp, "evidences", sa.Column("document_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("chunk_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("source_timestamp", sa.DateTime(), nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("claim_type", sa.String(50), server_default="source_excerpt", nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("metadata_json", sa.JSON(), nullable=True))

    # 8. Knowledge models
    _add_col_if_missing(insp, "knowledge_entities", sa.Column("source_record_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "knowledge_entities", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))
    _add_col_if_missing(insp, "knowledge_entities", sa.Column("updated_at", sa.DateTime(), nullable=True))

    _add_col_if_missing(insp, "knowledge_relationships", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))
    _add_col_if_missing(insp, "knowledge_relationships", sa.Column("source_record_id", sa.String(36), nullable=True))

    _add_col_if_missing(insp, "decisions", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))
    _add_col_if_missing(insp, "decisions", sa.Column("consequences", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "decisions", sa.Column("affected_components", sa.JSON(), nullable=True))

    _add_col_if_missing(insp, "task_items", sa.Column("component", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "task_items", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))

    _add_col_if_missing(insp, "dependencies", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))
    _add_col_if_missing(insp, "responsibilities", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))

    _add_col_if_missing(insp, "risk_items", sa.Column("impact", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "risk_items", sa.Column("owner", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "risk_items", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))

    _add_col_if_missing(insp, "knowledge_gaps", sa.Column("priority", sa.String(20), server_default="high", nullable=True))
    _add_col_if_missing(insp, "knowledge_gaps", sa.Column("business_impact", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "knowledge_gaps", sa.Column("technical_impact", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "knowledge_gaps", sa.Column("assigned_reviewer", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "knowledge_gaps", sa.Column("evidence_ids", sa.JSON(), nullable=True))

    # 9. Handovers
    _add_col_if_missing(insp, "handovers", sa.Column("target_date", sa.String(50), nullable=True))
    _add_col_if_missing(insp, "handovers", sa.Column("confidence_breakdown", sa.JSON(), nullable=True))
    _add_col_if_missing(insp, "handover_sections", sa.Column("verification_status", sa.String(50), server_default="Needs Human Verification", nullable=True))
    _add_col_if_missing(insp, "handover_sections", sa.Column("confidence", sa.Float(), server_default="0.0", nullable=True))
    _add_col_if_missing(insp, "handover_sections", sa.Column("metadata_json", sa.JSON(), nullable=True))

    _add_col_if_missing(insp, "handover_approvals", sa.Column("approver_user_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "handover_approvals", sa.Column("is_required", sa.Boolean(), server_default=sa.text("true"), nullable=True))
    _add_col_if_missing(insp, "handover_approvals", sa.Column("order_index", sa.Integer(), server_default="0", nullable=True))

    _add_col_if_missing(insp, "handover_versions", sa.Column("user_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "handover_versions", sa.Column("changed_section", sa.String(255), nullable=True))
    _add_col_if_missing(insp, "handover_versions", sa.Column("previous_content", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "handover_versions", sa.Column("new_content", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "handover_versions", sa.Column("reason", sa.Text(), nullable=True))

    # 10. PostgreSQL pgvector column + HNSW index + unique dedup constraints + consistent RLS
    if is_pg:
        insp = sa.inspect(bind)
        if not _has_column(insp, "embedding_records", "embedding_vector"):
            op.execute("ALTER TABLE embedding_records ADD COLUMN IF NOT EXISTS embedding_vector vector(384)")
        op.execute(
            "CREATE INDEX IF NOT EXISTS embedding_vec_hnsw_idx ON embedding_records "
            "USING hnsw (embedding_vector vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
        )
        # Deduplicate before adding unique constraints safely
        op.execute(
            "DELETE FROM project_members a USING project_members b "
            "WHERE a.ctid < b.ctid AND a.project_id = b.project_id AND a.user_id = b.user_id"
        )
        op.execute(
            "DELETE FROM source_records a USING source_records b "
            "WHERE a.ctid < b.ctid AND a.project_id = b.project_id "
            "AND a.source_type = b.source_type AND a.external_id = b.external_id"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_project_member_idx ON project_members(project_id, user_id)"
        )
        op.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_source_record_project_ext_idx "
            "ON source_records(project_id, source_type, external_id)"
        )
        # Consistent RLS helper combining FastAPI app.current_user_id GUC and Supabase auth.uid()
        op.execute(
            """
            CREATE OR REPLACE FUNCTION public.current_app_user_id()
            RETURNS text
            LANGUAGE sql
            STABLE
            AS $$
                SELECT COALESCE(
                    NULLIF(current_setting('app.current_user_id', true), ''),
                    auth.uid()::text
                );
            $$;
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute("DROP INDEX IF EXISTS embedding_vec_hnsw_idx")
        op.execute("DROP INDEX IF EXISTS uq_source_record_project_ext_idx")
        op.execute("DROP INDEX IF EXISTS uq_project_member_idx")
        op.execute("ALTER TABLE embedding_records DROP COLUMN IF EXISTS embedding_vector")
        op.execute("DROP FUNCTION IF EXISTS public.current_app_user_id()")

