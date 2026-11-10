# TEAM OBSIDIAN — AI-Powered Knowledge Handover & Project Intelligence Platform

TEAM OBSIDIAN converts scattered project activity across GitHub, Slack, Notion, and uploaded engineering documents into an evidence-verified Knowledge Graph and a structured **16-Section Handover Dossier** when team members transition or depart.

---

## Architecture Overview

- **Frontend (`code/frontend/`)**: Next.js `16.0.10` (App Router, Turbopack), React `19.2.0`, Tailwind CSS `4.1.9`, `@xyflow/react`, Recharts, Lucide icons.
- **Backend (`code/backend/`)**: FastAPI, SQLAlchemy `2.1+`, `psycopg` v3, Alembic (`migrations/`), Argon2id password hashing, PyJWT, Fernet encryption at rest, NetworkX, ReportLab PDF export.
- **AI & Semantic Retrieval**:
  - `BAAI/bge-small-en-v1.5` (384-dimensional dense embeddings via `fastembed`)
  - Hybrid RAG (`pgvector` cosine distance `<=>` with HNSW index + normalized token overlap)
  - Google Gemini (`google-genai` SDK: `gemini-2.5-flash` / `gemini-2.5-flash-lite`) with strict extractive fallback and honest ungrounded refusal when project evidence is missing
- **Database (`PostgreSQL + pgvector`)**: Supabase Cloud PostgreSQL with Row-Level Security (`backend/supabase_schema.sql`), Alembic schema management (`backend/alembic.ini`), and isolated SQLite support for automated tests.

---

## Security & Multi-Tenant Design

1. **Tenant Isolation & RBAC**: Organizations, Workspaces, Projects, and Project Members enforce cross-tenant access checks on every endpoint and Postgres RLS policy (`public.current_app_user_id()`, `public.user_can_access_project()`).
2. **9+ Supported Roles**: `org_admin`, `workspace_owner`, `project_owner`, `project_manager`, `tech_lead`, `developer`, `departing_employee`, `incoming_employee`, `viewer` (plus aliases like `reviewer`, `qa`).
3. **Authentication & Secrets**:
   - Passwords hashed with **Argon2id** (`argon2-cffi`), with automatic upgrade from legacy hashes upon successful login.
   - Passwords resets use single-use expiring SHA-256 tokens stored in `password_reset_tokens` and delivered via SMTP/Resend (or `backend/.dev_mail_outbox.log` locally) — never leaked in JSON responses.
   - Connector tokens encrypted at rest using Fernet (`CREDENTIALS_ENCRYPTION_KEY`) and masked on all read endpoints.
4. **Zero Hardcoded Customer Data**: Newly registered workspaces start completely empty with a clear onboarding flow. A synthetic E-Commerce demo dataset is available strictly via explicit opt-in (`POST /api/v1/seed/demo` or the empty-workspace sandbox button).

---

## Environment Configuration

Copy `code/backend/.env.example` to `code/backend/.env` and `code/frontend/.env.example` to `code/frontend/.env.local`:

```bash
# Required Backend Variables (code/backend/.env)
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
SECRET_KEY=<generate-strong-secret>
CREDENTIALS_ENCRYPTION_KEY=<generate-fernet-key>
GEMINI_API_KEY=<your-gemini-api-key>
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Optional Connector OAuth Credentials (for live GitHub/Slack/Notion OAuth flows)
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
NOTION_CLIENT_ID=
NOTION_CLIENT_SECRET=
```

Frontend (`code/frontend/.env.local`):

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

---

## Running Locally

### 1. Backend Setup & Database Migrations

```powershell
cd code/backend
pip install -r requirements.txt
python -m alembic upgrade head
python run.py
```

Backend API documentation is served at `http://localhost:8000/docs`.

### 2. Frontend Setup

```powershell
cd code/frontend
npm install --legacy-peer-deps
npm run dev
```

Application UI is served at `http://localhost:3000`.

---

## Automated Testing & Verification

### Backend Tests (`pytest`)

```powershell
cd code/backend
python -m pytest -v tests/
```

Covers multi-tenant isolation, RBAC, Argon2id hashing, password recovery lifecycle, controlled mock connector sync + deduplication, document chunking + SHA-256 provenance, real BGE semantic retrieval, Gemini AI grounding + unsupported-question refusal, NetworkX blast radius, and handover approval + PDF export.

*Note: Live external OAuth tests (`test_github_oauth_and_retrieval`, `test_slack_oauth_and_retrieval`, `test_notion_oauth_and_retrieval`) are skipped unless `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, and `NOTION_API_KEY` are configured in the environment.*

### Frontend Typecheck & Production Build

```powershell
cd code/frontend
npx tsc --noEmit
npm run build
```

### Browser E2E Verification (`Playwright`)

With backend running on `:8000` and frontend running on `:3000`:

```powershell
cd code
python -m pytest -v tests/test_playwright_e2e.py
```

Verifies auth flows, zero synthetic demo leakage, project creation & RBAC member management, document chunk inspection, grounded AI assistant + unsupported question refusal, knowledge graph canvas, 16-section handover reconstruction & authenticated PDF download, secret scanning, and mobile (`375x667`) responsiveness across all application routes.

---

## Deployment Instructions (Live Environment)

1. **PostgreSQL + pgvector (Supabase Cloud)**:
   - Provision a Supabase PostgreSQL project with the `vector` and `pg_trgm` extensions enabled.
   - Set `DATABASE_URL` to the IPv4 Session Pooler URI (`postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require`).
   - Run `python -m alembic upgrade head` inside `code/backend/` and apply `code/backend/supabase_schema.sql` via `supabase db query`.
2. **Backend (FastAPI — Render / Railway / Docker)**:
   - Deploy using the included Render Blueprint (`render.yaml`), Railway config (`backend/railway.json` + `backend/Dockerfile`), or `backend/Procfile`.
   - Set `APP_ENV=production`, a strong random 32+ char `SECRET_KEY`, a valid Fernet `CREDENTIALS_ENCRYPTION_KEY`, `GEMINI_API_KEY`, `FRONTEND_URL`, `BACKEND_URL`, comma-separated `CORS_ORIGINS` (e.g. `https://your-app.vercel.app`), and OAuth App credentials (`GITHUB_CLIENT_ID`/`SECRET`, `SLACK_CLIENT_ID`/`SECRET`, `NOTION_CLIENT_ID`/`SECRET`).
   - Configure provider OAuth callback URLs as `<BACKEND_URL>/api/v1/integrations/oauth/<provider>/callback`.
   - Production startup command: `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}` (or via `docker-compose.yml`).
3. **Frontend (Next.js — Vercel)**:
   - Deploy `frontend/` to Vercel (preconfigured with `frontend/vercel.json`) and set `NEXT_PUBLIC_API_URL=<BACKEND_URL>/api/v1` before building.
   - Build and serve with `npm run build && npm run start` (or via Vercel CLI `vercel --prod`).

