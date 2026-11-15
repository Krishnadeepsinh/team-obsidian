"""Security and Performance Optimizations: Document sha256 uniqueness, composite tenant indexes, pgvector HNSW

Revision ID: 004_security_perf_optimizations
Revises: 003_enterprise_scale_and_kt
Create Date: 2026-11-15
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "004_security_perf_optimizations"
down_revision: Union[str, Sequence[str], None] = "003_enterprise_scale_and_kt"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _create_idx_if_missing(insp, table: str, name: str, cols: list[str], unique: bool = False) -> None:
    if not _has_table(insp, table):
        return
    existing = {ix["name"] for ix in insp.get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, cols, unique=unique)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    # 1. Project-scoped document uniqueness
    _create_idx_if_missing(insp, "documents", "idx_doc_project_sha256", ["project_id", "sha256_hash"], unique=True)

    # 2. Composite indexes for tenant filtering and knowledge graph queries
    _create_idx_if_missing(insp, "knowledge_relationships", "idx_kr_project_rel_type", ["project_id", "relation_type"])
    _create_idx_if_missing(insp, "knowledge_entities", "idx_ke_project_type_name", ["project_id", "entity_type", "name"])
    _create_idx_if_missing(insp, "evidences", "idx_ev_project_status", ["project_id", "verification_status"])
    _create_idx_if_missing(insp, "decisions", "idx_decisions_project_date", ["project_id", "created_at"])
    _create_idx_if_missing(insp, "task_items", "idx_tasks_project_status_deadline", ["project_id", "status", "deadline"])
    _create_idx_if_missing(insp, "risk_items", "idx_risks_project_status_sev", ["project_id", "status", "severity"])

    # 3. PostgreSQL pgvector HNSW index
    if not is_sqlite:
        try:
            op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass
        if _has_table(insp, "embedding_records"):
            existing = {ix["name"] for ix in insp.get_indexes("embedding_records")}
            if "idx_embedding_vector_hnsw" not in existing:
                try:
                    op.execute(
                        "CREATE INDEX IF NOT EXISTS idx_embedding_vector_hnsw "
                        "ON embedding_records USING hnsw (embedding_vector vector_cosine_ops)"
                    )
                except Exception:
                    pass


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    for table, idx in [
        ("documents", "idx_doc_project_sha256"),
        ("knowledge_relationships", "idx_kr_project_rel_type"),
        ("knowledge_entities", "idx_ke_project_type_name"),
        ("evidences", "idx_ev_project_status"),
        ("decisions", "idx_decisions_project_date"),
        ("task_items", "idx_tasks_project_status_deadline"),
        ("risk_items", "idx_risks_project_status_sev"),
    ]:
        if _has_table(insp, table):
            try:
                op.drop_index(idx, table_name=table)
            except Exception:
                pass

