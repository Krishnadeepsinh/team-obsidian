"""enterprise rls hardening and policy enforcement

Revision ID: 006_enterprise_rls_hardening
Revises: 005_enterprise_org_integrations
Create Date: 2026-11-16 00:40:00.000000
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "006_enterprise_rls_hardening"
down_revision: Union[str, None] = "005_enterprise_org_integrations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        # 1. Enable and Force RLS on integration_project_access & integrations
        op.execute("ALTER TABLE integration_project_access ENABLE ROW LEVEL SECURITY;")
        try:
            op.execute("ALTER TABLE integration_project_access FORCE ROW LEVEL SECURITY;")
        except Exception:
            pass

        try:
            op.execute("ALTER TABLE integrations FORCE ROW LEVEL SECURITY;")
        except Exception:
            pass

        # 2. Update obsidian_integrations_isolation policy
        op.execute("DROP POLICY IF EXISTS \"obsidian_integrations_isolation\" ON integrations;")
        op.execute("""
            CREATE POLICY "obsidian_integrations_isolation" ON integrations
            FOR ALL USING (
                (authorized_by_user_id IS NOT NULL AND (authorized_by_user_id)::text = public.current_app_user_id())
                OR ((user_id)::text = public.current_app_user_id())
                OR (
                    connection_type = 'organization'
                    AND (
                        public.user_can_access_project(project_id)
                        OR EXISTS (
                            SELECT 1 FROM integration_project_access ipa
                            WHERE ipa.integration_id = integrations.id
                              AND public.user_can_access_project(ipa.project_id)
                        )
                    )
                )
            );
        """)

        # 3. Create obsidian_integration_project_access_isolation policy
        op.execute("DROP POLICY IF EXISTS \"obsidian_integration_project_access_isolation\" ON integration_project_access;")
        op.execute("""
            CREATE POLICY "obsidian_integration_project_access_isolation" ON integration_project_access
            FOR ALL USING (
                public.user_can_access_project(project_id)
                OR EXISTS (
                    SELECT 1 FROM integrations i
                    WHERE i.id = integration_id
                      AND (
                          (i.authorized_by_user_id IS NOT NULL AND (i.authorized_by_user_id)::text = public.current_app_user_id())
                          OR ((i.user_id)::text = public.current_app_user_id())
                      )
                )
            );
        """)


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if not is_sqlite:
        op.execute("DROP POLICY IF EXISTS \"obsidian_integration_project_access_isolation\" ON integration_project_access;")
        op.execute("DROP POLICY IF EXISTS \"obsidian_integrations_isolation\" ON integrations;")
        op.execute("""
            CREATE POLICY "obsidian_integrations_isolation" ON integrations
            FOR ALL USING (((user_id)::text = public.current_app_user_id()) OR public.user_can_access_project(project_id));
        """)
        op.execute("ALTER TABLE integration_project_access DISABLE ROW LEVEL SECURITY;")
