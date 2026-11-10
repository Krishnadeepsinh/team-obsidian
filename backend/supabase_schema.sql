-- ==============================================================================
-- TEAM OBSIDIAN: Production Supabase PostgreSQL Schema with pgvector & Unified RLS
-- Multi-User & Multi-Tenant SaaS Architecture
-- Note: Uses VARCHAR(36) UUID strings compatible with SQLAlchemy ORM & FastAPI JWTs
-- ==============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Unified Identity Helper: works with BOTH FastAPI `SET LOCAL app.current_user_id` AND Supabase `auth.uid()`
CREATE OR REPLACE FUNCTION public.current_app_user_id()
RETURNS text
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT COALESCE(
        NULLIF(current_setting('app.current_user_id', true), ''),
        auth.uid()::text
    );
$$;

-- Helper: Check if current user can access a given project_id
CREATE OR REPLACE FUNCTION public.user_can_access_project(p_id varchar)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_temp
AS $$
    SELECT EXISTS (
        SELECT 1 FROM projects p
        WHERE p.id = p_id
          AND (
              p.creator_id = public.current_app_user_id()
              OR EXISTS (
                  SELECT 1 FROM project_members pm
                  WHERE pm.project_id = p.id
                    AND pm.user_id = public.current_app_user_id()
                    AND pm.status IN ('active', 'departing', 'incoming')
              )
              OR EXISTS (
                  SELECT 1 FROM workspaces w
                  WHERE w.id = p.workspace_id
                    AND (
                        w.owner_id = public.current_app_user_id()
                        OR (
                            w.is_personal = false
                            AND EXISTS (
                                SELECT 1 FROM organizations o
                                JOIN users u ON u.org_id = o.id
                                WHERE o.id = w.org_id
                                  AND u.id = public.current_app_user_id()
                                  AND (o.owner_id = u.id OR u.role IN ('admin', 'org_admin'))
                            )
                        )
                    )
              )
          )
    );
$$;

-- Enable RLS across all tenant-scoped tables
ALTER TABLE IF EXISTS organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS users ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS password_reset_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS source_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS source_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS evidences ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS evidence_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS task_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS dependencies ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS responsibilities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS risk_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS knowledge_gaps ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS knowledge_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS knowledge_relationships ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS embedding_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS handovers ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS handover_sections ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS handover_claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS handover_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS handover_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS activity_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS notifications ENABLE ROW LEVEL SECURITY;

-- Drop legacy policies if present so script is safely re-runnable
DO $$
DECLARE
    pol record;
BEGIN
    FOR pol IN
        SELECT schemaname, tablename, policyname
        FROM pg_policies
        WHERE schemaname = 'public'
    LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I.%I', pol.policyname, pol.schemaname, pol.tablename);
    END LOOP;
END $$;

-- Organizations
CREATE POLICY "obsidian_org_isolation" ON organizations
    FOR ALL USING (
        owner_id = public.current_app_user_id()
        OR id IN (SELECT org_id FROM users WHERE id = public.current_app_user_id())
    );

-- Workspaces
CREATE POLICY "obsidian_workspace_isolation" ON workspaces
    FOR ALL USING (
        owner_id = public.current_app_user_id()
        OR (
            is_personal = false
            AND org_id IN (SELECT org_id FROM users WHERE id = public.current_app_user_id())
        )
    );

-- Users (own record or shared non-personal org / shared project)
CREATE POLICY "obsidian_users_isolation" ON users
    FOR ALL USING (
        id = public.current_app_user_id()
        OR id IN (
            SELECT pm2.user_id FROM project_members pm1
            JOIN project_members pm2 ON pm1.project_id = pm2.project_id
            WHERE pm1.user_id = public.current_app_user_id()
        )
    );

-- Password reset tokens (strictly own user)
CREATE POLICY "obsidian_reset_tokens_isolation" ON password_reset_tokens
    FOR ALL USING (user_id = public.current_app_user_id());

-- Projects & Members
CREATE POLICY "obsidian_projects_isolation" ON projects
    FOR ALL USING (public.user_can_access_project(id));

CREATE POLICY "obsidian_project_members_isolation" ON project_members
    FOR ALL USING (public.user_can_access_project(project_id));

-- Project-scoped tables
CREATE POLICY "obsidian_integrations_isolation" ON integrations
    FOR ALL USING (user_id = public.current_app_user_id() OR public.user_can_access_project(project_id));

CREATE POLICY "obsidian_source_records_isolation" ON source_records
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_source_events_isolation" ON source_events
    FOR ALL USING (
        integration_id IN (SELECT id FROM integrations WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_documents_isolation" ON documents
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_document_chunks_isolation" ON document_chunks
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_evidences_isolation" ON evidences
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_evidence_reviews_isolation" ON evidence_reviews
    FOR ALL USING (
        evidence_id IN (SELECT id FROM evidences WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_decisions_isolation" ON decisions
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_tasks_isolation" ON task_items
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_dependencies_isolation" ON dependencies
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_responsibilities_isolation" ON responsibilities
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_risks_isolation" ON risk_items
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_gaps_isolation" ON knowledge_gaps
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_entities_isolation" ON knowledge_entities
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_relationships_isolation" ON knowledge_relationships
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_embeddings_isolation" ON embedding_records
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_handovers_isolation" ON handovers
    FOR ALL USING (public.user_can_access_project(project_id));

CREATE POLICY "obsidian_handover_sections_isolation" ON handover_sections
    FOR ALL USING (
        handover_id IN (SELECT id FROM handovers WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_handover_claims_isolation" ON handover_claims
    FOR ALL USING (
        handover_id IN (SELECT id FROM handovers WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_handover_approvals_isolation" ON handover_approvals
    FOR ALL USING (
        handover_id IN (SELECT id FROM handovers WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_handover_versions_isolation" ON handover_versions
    FOR ALL USING (
        handover_id IN (SELECT id FROM handovers WHERE public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_activity_logs_isolation" ON activity_logs
    FOR ALL USING (
        user_id = public.current_app_user_id()
        OR (project_id IS NOT NULL AND public.user_can_access_project(project_id))
    );

CREATE POLICY "obsidian_notifications_isolation" ON notifications
    FOR ALL USING (user_id = public.current_app_user_id());

-- Lock down anonymous PostgREST role on all application tables
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon;
