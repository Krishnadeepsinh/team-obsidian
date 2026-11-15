"""Enterprise Organization-Level Integration Architecture

Revision ID: 005_enterprise_org_integrations
Revises: 004_security_perf_optimizations
Create Date: 2026-11-16
"""
import uuid
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "005_enterprise_org_integrations"
down_revision: Union[str, Sequence[str], None] = "004_security_perf_optimizations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(insp, name: str) -> bool:
    return name in insp.get_table_names()


def _has_column(insp, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(c["name"] == column for c in insp.get_columns(table))


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

    # 1. Add new columns to integrations table if not present
    if not _has_column(insp, "integrations", "workspace_id"):
        op.add_column("integrations", sa.Column("workspace_id", sa.String(36), nullable=True))
        if not is_sqlite:
            op.create_foreign_key(
                "fk_integrations_workspace_id",
                "integrations",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )

    if not _has_column(insp, "integrations", "connection_type"):
        op.add_column("integrations", sa.Column("connection_type", sa.String(50), nullable=True, server_default="organization"))

    if not _has_column(insp, "integrations", "external_org_id"):
        op.add_column("integrations", sa.Column("external_org_id", sa.String(255), nullable=True))

    if not _has_column(insp, "integrations", "external_org_name"):
        op.add_column("integrations", sa.Column("external_org_name", sa.String(255), nullable=True))

    if not _has_column(insp, "integrations", "authorized_by_user_id"):
        op.add_column("integrations", sa.Column("authorized_by_user_id", sa.String(36), nullable=True))
        if not is_sqlite:
            op.create_foreign_key(
                "fk_integrations_authorized_by_user_id",
                "integrations",
                "users",
                ["authorized_by_user_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if not _has_column(insp, "integrations", "authorized_by_email"):
        op.add_column("integrations", sa.Column("authorized_by_email", sa.String(255), nullable=True))

    if not _has_column(insp, "integrations", "token_expires_at"):
        op.add_column("integrations", sa.Column("token_expires_at", sa.DateTime(), nullable=True))

    if not _has_column(insp, "integrations", "assigned_projects"):
        op.add_column("integrations", sa.Column("assigned_projects", sa.JSON(), nullable=True))

    # 2. Add indexes on integrations table
    _create_idx_if_missing(insp, "integrations", "idx_integrations_workspace_id", ["workspace_id"])
    _create_idx_if_missing(insp, "integrations", "idx_integrations_external_org", ["external_org_id"])
    _create_idx_if_missing(insp, "integrations", "idx_integrations_auth_user", ["authorized_by_user_id"])

    # 3. Create integration_project_access table if missing
    if not _has_table(insp, "integration_project_access"):
        op.create_table(
            "integration_project_access",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("integration_id", sa.String(36), sa.ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()" if not is_sqlite else "CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("integration_id", "project_id", name="uq_integration_project_access"),
        )
        _create_idx_if_missing(insp, "integration_project_access", "idx_ipa_integration_project", ["integration_id", "project_id"])

    # 4. Data Backfill
    try:
        if not is_sqlite:
            # Backfill workspace_id from projects
            op.execute("""
                UPDATE integrations
                SET workspace_id = projects.workspace_id
                FROM projects
                WHERE integrations.project_id = projects.id
                  AND integrations.workspace_id IS NULL;
            """)
            # Backfill authorized_by_user_id and authorized_by_email from users
            op.execute("""
                UPDATE integrations
                SET authorized_by_user_id = integrations.user_id
                WHERE integrations.authorized_by_user_id IS NULL AND integrations.user_id IS NOT NULL;
            """)
            op.execute("""
                UPDATE integrations
                SET authorized_by_email = users.email
                FROM users
                WHERE integrations.authorized_by_user_id = users.id
                  AND integrations.authorized_by_email IS NULL;
            """)
            # Ensure connection_type is default 'organization'
            op.execute("""
                UPDATE integrations
                SET connection_type = 'organization'
                WHERE connection_type IS NULL;
            """)
            # Insert integration_project_access for existing integrations
            op.execute("""
                INSERT INTO integration_project_access (id, integration_id, project_id, created_at)
                SELECT gen_random_uuid()::text, i.id, i.project_id, COALESCE(i.created_at, now())
                FROM integrations i
                WHERE i.project_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM integration_project_access ipa
                      WHERE ipa.integration_id = i.id AND ipa.project_id = i.project_id
                  );
            """)
            # Clean up the erroneous Linear & Sentry rows attached to Vaghela's project from chudasamakrishnadeep3
            op.execute("""
                DELETE FROM integrations
                WHERE id IN ('321e3c2a-b8c7-4c82-a56c-f0a8ef2fe003', '28e2cc73-8579-49f6-abe1-6f3255c24a81')
                  AND connected_account = 'chudasamakrishnadeep3@gmail.com';
            """)
    except Exception as exc:
        print(f"Warning during migration 005 backfill: {exc}")


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if _has_table(insp, "integration_project_access"):
        op.drop_table("integration_project_access")

    for col in [
        "assigned_projects",
        "token_expires_at",
        "authorized_by_email",
        "authorized_by_user_id",
        "external_org_name",
        "external_org_id",
        "connection_type",
        "workspace_id",
    ]:
        if _has_column(insp, "integrations", col):
            op.drop_column("integrations", col)

