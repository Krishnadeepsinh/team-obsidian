-- ==============================================================================
-- Migration 002: Multi-User, Multi-Tenant SaaS Architecture
-- Supports:
-- 1. Personal Workspaces & Organizations
-- 2. User-specific Integrations & Tokens
-- 3. Project Membership Access Control
-- 4. User-scoped Knowledge, Handovers, and Documents
-- ==============================================================================

-- 1. Add owner_id and is_personal to organizations & workspaces
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);
ALTER TABLE organizations ADD COLUMN IF NOT EXISTS is_personal BOOLEAN DEFAULT false;

ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS owner_id VARCHAR(36);
ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS is_personal BOOLEAN DEFAULT false;

-- 2. Add personal_workspace_id to users
ALTER TABLE users ADD COLUMN IF NOT EXISTS personal_workspace_id VARCHAR(36);

-- 3. Add creator_id to projects
ALTER TABLE projects ADD COLUMN IF NOT EXISTS creator_id VARCHAR(36);

-- 4. Add user_id and is_org_level to integrations
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);
ALTER TABLE integrations ADD COLUMN IF NOT EXISTS is_org_level BOOLEAN DEFAULT false;

-- 5. Add user_id to documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS user_id VARCHAR(36);

-- 6. Add created_by_user_id to handovers, decisions, tasks, risks, entities
ALTER TABLE handovers ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36);
ALTER TABLE decisions ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36);
ALTER TABLE task_items ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36);
ALTER TABLE risk_items ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36);
ALTER TABLE knowledge_entities ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(36);

-- Indexes for efficient multi-tenant queries
CREATE INDEX IF NOT EXISTS idx_orgs_owner_id ON organizations(owner_id);
CREATE INDEX IF NOT EXISTS idx_workspaces_owner_id ON workspaces(owner_id);
CREATE INDEX IF NOT EXISTS idx_users_personal_ws ON users(personal_workspace_id);
CREATE INDEX IF NOT EXISTS idx_projects_creator ON projects(creator_id);
CREATE INDEX IF NOT EXISTS idx_integrations_user ON integrations(user_id);
CREATE INDEX IF NOT EXISTS idx_documents_user ON documents(user_id);
CREATE INDEX IF NOT EXISTS idx_handovers_creator ON handovers(created_by_user_id);

-- Enable RLS on all tenant tables
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE integrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk_items ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_gaps ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidences ENABLE ROW LEVEL SECURITY;
ALTER TABLE handovers ENABLE ROW LEVEL SECURITY;
ALTER TABLE handover_sections ENABLE ROW LEVEL SECURITY;

