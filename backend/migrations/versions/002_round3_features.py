"""Round 3 features: durable storage columns, knowledge drift events, readiness simulations

Revision ID: 002_round3_features
Revises: 001_phase1_phase2
Create Date: 2026-11-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "002_round3_features"
down_revision: Union[str, Sequence[str], None] = "001_phase1_phase2"
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

    _add_col_if_missing(insp, "documents", sa.Column("storage_bucket", sa.String(120), nullable=True))
    _add_col_if_missing(insp, "documents", sa.Column("storage_key", sa.String(500), nullable=True))

    if not _has_table(insp, "knowledge_drift_events"):
        op.create_table(
            "knowledge_drift_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("integration_id", sa.String(36), nullable=True),
            sa.Column("source_record_id", sa.String(36), nullable=True),
            sa.Column("drift_type", sa.String(50), nullable=False, server_default="contradiction"),
            sa.Column("severity", sa.String(20), nullable=False, server_default="high"),
            sa.Column("target_entity_type", sa.String(50), nullable=False, server_default="decision"),
            sa.Column("target_entity_id", sa.String(36), nullable=False),
            sa.Column("target_title", sa.String(500), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("evidence_excerpt", sa.Text(), nullable=True),
            sa.Column("status", sa.String(30), nullable=False, server_default="open"),
            sa.Column("resolved_by_user_id", sa.String(36), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
        )
        op.create_index("idx_drift_project_status", "knowledge_drift_events", ["project_id", "status"])

    if not _has_table(insp, "readiness_simulations"):
        op.create_table(
            "readiness_simulations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("handover_id", sa.String(36), sa.ForeignKey("handovers.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("user_id", sa.String(36), nullable=True, index=True),
            sa.Column("candidate_name", sa.String(255), nullable=False),
            sa.Column("overall_score", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("scenarios_json", sa.JSON(), nullable=True),
            sa.Column("responses_json", sa.JSON(), nullable=True),
            sa.Column("summary_feedback", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True, index=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if _has_table(insp, "readiness_simulations"):
        op.drop_table("readiness_simulations")
    if _has_table(insp, "knowledge_drift_events"):
        op.drop_table("knowledge_drift_events")

