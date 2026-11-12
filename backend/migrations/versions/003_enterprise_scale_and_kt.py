"""Enterprise Scale & KT Upgrade: AST/Chunking columns, ExitInterviewQuestion, PipelineJob, composite & HNSW indexes

Revision ID: 003_enterprise_scale_and_kt
Revises: 002_round3_features
Create Date: 2026-11-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "003_enterprise_scale_and_kt"
down_revision: Union[str, Sequence[str], None] = "002_round3_features"
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


def _create_idx_if_missing(insp, table: str, name: str, cols: list[str]) -> None:
    if not _has_table(insp, table):
        return
    existing = {ix["name"] for ix in insp.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, cols)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    # Phase 1-2 additive columns
    _add_col_if_missing(insp, "evidences", sa.Column("parent_evidence_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("total_chunks", sa.Integer(), server_default="1", nullable=True))
    _add_col_if_missing(insp, "evidences", sa.Column("full_text", sa.Text(), nullable=True))
    _add_col_if_missing(insp, "embedding_records", sa.Column("parent_id", sa.String(36), nullable=True))
    _add_col_if_missing(insp, "embedding_records", sa.Column("chunk_index", sa.Integer(), server_default="0", nullable=True))
    _add_col_if_missing(
        insp,
        "embedding_records",
        sa.Column("task_type", sa.String(40), server_default="RETRIEVAL_DOCUMENT", nullable=True),
    )
    _add_col_if_missing(insp, "source_records", sa.Column("extraction_processed_at", sa.DateTime(), nullable=True))

    # Phase 3: Exit Interview Q&A persistence table
    if not _has_table(insp, "exit_interview_questions"):
        op.create_table(
            "exit_interview_questions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("handover_id", sa.String(36), sa.ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("section_number", sa.Integer(), nullable=True),
            sa.Column("knowledge_gap_id", sa.String(36), sa.ForeignKey("knowledge_gaps.id", ondelete="SET NULL"), nullable=True),
            sa.Column("question_text", sa.Text(), nullable=False),
            sa.Column("answer_text", sa.Text(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("priority", sa.String(20), nullable=False, server_default="high"),
            sa.Column("evidence_id", sa.String(36), nullable=True),
            sa.Column("created_by_user_id", sa.String(36), nullable=True),
            sa.Column("answered_by_user_id", sa.String(36), nullable=True),
            sa.Column("answered_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    # Phase 4: Durable PipelineJob table
    if not _has_table(insp, "pipeline_jobs"):
        op.create_table(
            "pipeline_jobs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("integration_id", sa.String(36), sa.ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True, index=True),
            sa.Column("job_type", sa.String(80), nullable=False, server_default="knowledge_extraction"),
            sa.Column("stage", sa.String(60), nullable=False, server_default="queued"),
            sa.Column("status", sa.String(30), nullable=False, server_default="running"),
            sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("message", sa.Text(), nullable=True),
            sa.Column("details", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True, index=True),
        )

    # Re-inspect after new tables/columns
    insp = sa.inspect(bind)
    _create_idx_if_missing(insp, "source_records", "idx_source_record_project_proc", ["project_id", "extraction_processed_at"])
    _create_idx_if_missing(insp, "embedding_records", "idx_embedding_project_entity", ["project_id", "entity_type", "entity_id"])
    _create_idx_if_missing(insp, "embedding_records", "idx_embedding_project_parent", ["project_id", "parent_id"])
    _create_idx_if_missing(insp, "embedding_records", "idx_embedding_project_task", ["project_id", "task_type"])
    _create_idx_if_missing(insp, "evidences", "idx_evidence_project_status", ["project_id", "verification_status"])
    _create_idx_if_missing(insp, "evidences", "idx_evidence_project_parent", ["project_id", "parent_evidence_id"])
    _create_idx_if_missing(insp, "knowledge_entities", "idx_ke_project_type", ["project_id", "entity_type"])
    _create_idx_if_missing(insp, "knowledge_relationships", "idx_kr_project_src_dst", ["project_id", "source_entity_id", "target_entity_id"])
    _create_idx_if_missing(insp, "task_items", "idx_task_project_owner", ["project_id", "owner"])
    _create_idx_if_missing(insp, "exit_interview_questions", "idx_exit_q_handover_status", ["handover_id", "status"])
    _create_idx_if_missing(insp, "pipeline_jobs", "idx_pipeline_job_proj_updated", ["project_id", "updated_at"])
    _create_idx_if_missing(insp, "pipeline_jobs", "idx_pipeline_job_integ_updated", ["integration_id", "updated_at"])

    if bind.dialect.name == "postgresql":
        try:
            op.execute(
                "CREATE INDEX IF NOT EXISTS idx_embedding_vector_hnsw "
                "ON embedding_records USING hnsw (embedding_vector vector_cosine_ops)"
            )
        except Exception:
            pass


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS idx_embedding_vector_hnsw")
    op.drop_table("pipeline_jobs")
    op.drop_table("exit_interview_questions")

