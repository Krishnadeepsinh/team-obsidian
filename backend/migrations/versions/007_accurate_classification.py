"""accurate connection classification for enterprise integrations

Revision ID: 007_accurate_classification
Revises: 006_enterprise_rls_hardening
Create Date: 2026-11-16 01:10:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "007_accurate_classification"
down_revision: Union[str, None] = "006_enterprise_rls_hardening"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        # Reclassify personal connections based on provider patterns
        # 1. GitHub without app installation
        op.execute("""
            UPDATE integrations
            SET connection_type = 'personal',
                is_org_level = false
            WHERE provider = 'github'
              AND external_org_id IS NULL;
        """)

        # 2. GitLab without group level binding
        op.execute("""
            UPDATE integrations
            SET connection_type = 'personal',
                is_org_level = false
            WHERE provider = 'gitlab'
              AND external_org_id IS NULL;
        """)

        # 3. Sentry user auth tokens (sntryu_...)
        op.execute("""
            UPDATE integrations
            SET connection_type = 'personal',
                is_org_level = false
            WHERE provider = 'sentry'
              AND (name ILIKE '%personal%' OR connected_account ILIKE '%@%');
        """)

        # 4. Remove integration_project_access records for personal connections so they cannot be shared across projects
        op.execute("""
            DELETE FROM integration_project_access
            WHERE integration_id IN (
                SELECT id FROM integrations WHERE connection_type = 'personal'
            );
        """)


def downgrade() -> None:
    pass
