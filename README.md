# TEAM OBSIDIAN — AI-Powered Knowledge Handover & Project Intelligence Platform

**TEAM OBSIDIAN** transforms scattered engineering context across **GitHub**, **Slack**, **Notion**, and uploaded project documents into an evidence-verified Knowledge Graph, a grounded RAG Project Assistant, and an audit-ready **16-Section Handover Dossier** when engineers transition or depart.

- **Live Web App (Vercel):** https://team-obsidian.vercel.app
- **Live Backend API (Render):** https://team-obsidian-api.onrender.com
- **Interactive API Docs:** https://team-obsidian-api.onrender.com/docs
- **Architecture & Workflow Guide:** [`WORKFLOW.md`](WORKFLOW.md)

### Team (`TEAM-OBSIDIAN`)
- Vaghela Yagnadeepsinh Chetansinh
- Makwana Tushar Shantibhai
- Chauhan Jaydip Pankajbhai
- Chudasama Krishnadeepsinh Shaktisinh

---

## Core Features Implemented

1. **Multi-Tenant Auth & RBAC**: Registration, Login, Argon2id password hashing, HS256 JWT sessions, Organization -> Workspace -> Project hierarchy, 9+ project roles (`org_admin`, `workspace_owner`, `project_owner`, `project_manager`, `tech_lead`, `developer`, `departing_employee`, `incoming_employee`, `viewer`), profile management, and in-app password updates.
2. **Live Integrations with Interactive Target Picker (`/integrations`)**:
   - Connects **GitHub**, **Slack**, and **Notion** via OAuth 2.0 or API/PAT/Bot tokens.
   - **Live Resource Discovery**: Fetches accessible GitHub repositories (with `/user/installations` fallback for GitHub App tokens and `refresh_token` rotation), Slack channels (showing bot membership status), and Notion pages/databases into a searchable multi-select checklist before saving or after OAuth redirect.
   - Deduplicated incremental sync via SHA-256 content hashes, sync cursors, and asynchronous background extraction.
3. **Multi-Format Document Library (`/documents`)**:
   - Uploads `.pdf`, `.docx`, `.xlsx`, `.md`, `.txt`, `.csv`, `.html`, `.json`, `.yaml`, `.yml`, `.log`, `.rst`, `.sql`, and `.xml` files (up to 25 MB).
   - Validates legacy binary types and unreadable scanned PDFs, strips PostgreSQL NUL bytes safely, builds inspectable structural chunks with SHA-256 hashes, and indexes embeddings in background tasks.
4. **Evidence Center (`/evidence`)**: Filter extracted claims by verification status (`Draft / AI Suggested`, `Supported by Evidence`, `Needs Human Verification`, `Verified by Reviewer`, `Contradicted`, `Outdated`, `Unknown / Missing Evidence`) and record human audit reviews.
5. **AI Knowledge Extraction & Knowledge Graph (`/knowledge/graph`, `/knowledge/dependencies`)**:
   - Google Gemini structured extraction (`StructuredKnowledgeBundle`) into typed Entities, Relationships, ADRs, Tasks, Risks, Dependencies, Responsibilities, and Knowledge Gaps.
   - Interactive `@xyflow/react` graph canvas + NetworkX blast-radius and Single-Point-of-Failure (SPOF) detection.
6. **Evidence-Grounded AI Assistant (`/assistant`) & Global Search (`/knowledge/explorer`)**:
   - Hybrid `pgvector` HNSW cosine similarity + normalized keyword retrieval (`gemini-embedding-001` 384-dim in production, optional local `BAAI/bge-small-en-v1.5` fallback in development).
   - Clickable evidence citations, confidence breakdown, strict ungrounded refusal when project evidence is missing, and `⌘K` / `Ctrl+K` global search bar routing cleanly to `/knowledge/explorer?search=`.
7. **Engineering & Transition Trackers (`/decisions`, `/tasks`, `/risks`, `/gaps`)**: Full tracking for Architectural Decision Records, departing-owner task filtering & successor reassignment, risk mitigation, and open/resolved knowledge gaps.
8. **16-Section Handover Dossier Workflow (`/handover`, `/handover/approvals`, `/handover/history`)**:
   - Reconstruction Wizard with source/category filtering and custom approver assignment.
   - Section-by-section markdown editing, reviewer comments, claim verification, immutable version diff history, multi-role sign-off workflow, and **ReportLab PDF export**.
9. **Observability & Governance (`/timeline`, `/activity`, `/logs`, `/team`, `/notifications`, `/settings`)**: Project chronological timeline, org audit logs, team directory, notifications, and workspace governance thresholds.

---

## Architecture Overview

- **Frontend (`frontend/`)**: Next.js `16.4.6` (App Router, Turbopack), React `19.2.0`, TypeScript, Tailwind CSS `v4`, `@xyflow/react`, Recharts, Lucide icons (`31` built routes).
- **Backend (`backend/`)**: FastAPI, SQLAlchemy `2.x`, Alembic (`backend/migrations/`), `psycopg` v3, `argon2-cffi`, PyJWT, `cryptography` (Fernet), NetworkX, PyMuPDF, `python-docx`, `openpyxl`, BeautifulSoup4, ReportLab.
- **Database (`PostgreSQL + pgvector`)**: Supabase Cloud PostgreSQL with `pgvector` HNSW vector index, Row-Level Security (`backend/supabase_schema.sql`), Alembic migrations, and isolated SQLite support for offline unit tests.
- **AI & Retrieval**:
  - Production Embeddings: `gemini-embedding-001` (384-dim via `v1beta` REST client, avoiding container ONNX memory spikes on 512 MB instances); optional local `BAAI/bge-small-en-v1.5` via `fastembed`.
  - Generation: `google-genai` SDK with configurable `PRIMARY_LLM` / `SECONDARY_LLM` and automatic fallback across Gemini Flash / Flash-Lite models + strict extractive fallback when API quota is unavailable.

---

## Repository Structure

```text
code/
├── README.md                  # Project overview, setup, testing, and deployment guide
├── WORKFLOW.md                # Full architecture diagram, 8-stage workflow & route map
├── render.yaml                # Render Blueprint for backend deployment
├── docker-compose.yml         # Local containerized runtime
├── backend/
│   ├── alembic.ini & migrations/
│   ├── requirements.txt
│   ├── supabase_schema.sql    # pgvector + RLS schema helpers
│   ├── run.py
│   ├── app/
│   │   ├── api/v1/            # auth, projects, integrations, documents, evidence,
│   │   │                      # knowledge, graph, assistant, handover, decisions, tasks, risks, gaps, team
│   │   ├── core/              # config, database, permissions (RBAC), security (Argon2id/JWT/Fernet)
│   │   ├── models/            # workspace, integration, evidence, knowledge, handover SQLAlchemy models
│   │   ├── schemas/           # Pydantic request/response contracts
│   │   └── services/          # connectors/ (github, slack, notion), ai_engine, document_parser,
│   │                          # knowledge_extractor, rag_assistant, graph_analytics, handover_builder, pdf_exporter
│   └── tests/                 # pytest suite (56 tests covering SaaS isolation, connectors, upload, RAG, PDF)
└── frontend/
    ├── package.json
    ├── vercel.json
    ├── lib/api.ts             # Authenticated API client, cold-start retry backoff, active project resolver
    ├── components/            # AppShell (sidebar, project switcher, Cmd+K search) & UI primitives
    └── app/                   # Next.js App Router pages across all 31 routes
```

---

## Security & Multi-Tenant Design

1. **Tenant Isolation & RBAC**: Every endpoint validates project/workspace membership (`verify_project_access`) alongside PostgreSQL RLS policies (`public.current_app_user_id()`, `public.user_can_access_project()`).
2. **Encryption at Rest & Redaction**: OAuth/API tokens are encrypted via Fernet (`CREDENTIALS_ENCRYPTION_KEY`) before database storage and masked (`***`) in every API response.
3. **Password Hygiene**: Passwords use Argon2id hashing; password recovery issues single-use SHA-256 tokens (`password_reset_tokens`) delivered out-of-band without leaking reset tokens in API responses.
4. **Zero Hardcoded Customer Data**: New workspaces start clean and isolated. A synthetic demo dataset is available strictly via explicit API call (`POST /api/v1/seed/demo`).

---

## Environment Configuration

Copy `backend/.env.example` -> `backend/.env` and `frontend/.env.example` -> `frontend/.env.local`:

```bash
# backend/.env
APP_ENV=development
DATABASE_URL=postgresql+psycopg://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
SECRET_KEY=<64-char-random-hex>
CREDENTIALS_ENCRYPTION_KEY=<fernet-base64-key>
GEMINI_API_KEY=<your-gemini-api-key>
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
FRONTEND_URL=http://localhost:3000
BACKEND_URL=http://localhost:8000

# Optional OAuth & Dev Connector Tokens
GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
SLACK_CLIENT_ID=
SLACK_CLIENT_SECRET=
NOTION_CLIENT_ID=
NOTION_CLIENT_SECRET=
```

```bash
# frontend/.env.local
NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
```

---

## Running Locally

### 1. Backend API
```powershell
cd backend
pip install -r requirements.txt
python -m alembic upgrade head
python run.py
```
Swagger docs: `http://localhost:8000/docs`

### 2. Frontend Web App
```powershell
cd frontend
npm install --legacy-peer-deps
npm run dev
```
App URL: `http://localhost:3000`

---

## Automated Verification & Builds

### Backend Tests (`pytest` — 56 tests)
```powershell
cd backend
python -m pytest -v tests/
```
Covers integration resource discovery & refresh tokens, multi-format document resilience, Argon2id & password reset lifecycle, cross-tenant SaaS isolation & RBAC, real semantic retrieval, Gemini grounding + ungrounded refusal, NetworkX blast radius, and handover approvals + ReportLab PDF export.  
*(Note: Live GitHub/Slack/Notion retrieval tests skip automatically if `GITHUB_TOKEN`, `SLACK_BOT_TOKEN`, or `NOTION_API_KEY` are unset.)*

### Frontend Lint, Typecheck & Production Build
```powershell
cd frontend
npm run lint
npx tsc --noEmit
npm run build
```

---

## Production Deployment & Current Limitations

1. **Supabase PostgreSQL + pgvector**: Run `python -m alembic upgrade head` and apply `backend/supabase_schema.sql`. Use the IPv4 Session Pooler URI for `DATABASE_URL`.
2. **Backend (Render)**: Configured via [`render.yaml`](render.yaml) (`rootDir: backend`, startup runs `python -m alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`). Configure `<BACKEND_URL>/api/v1/integrations/oauth/<provider>/callback` in GitHub/Slack/Notion OAuth settings.
3. **Frontend (Vercel)**: Deploy `frontend/` with `NEXT_PUBLIC_API_URL=https://<backend-host>/api/v1`.

**Known Production Caveats (Round 2):**
- Outbound SMTP/Resend credentials are not yet configured in the live Render environment (`email_delivery_configured: false`), so live forgot-password emails are disabled (in-app password change works on `/profile`).
- Uploaded raw file binaries are written to Render's ephemeral disk (`uploads/`) rather than durable S3/Supabase Object Storage (extracted text, chunks, SHA-256 hashes, embeddings, and Evidence rows remain persistent in Supabase PostgreSQL).
- Image-only scanned PDFs without selectable text require OCR and return a clear validation error.
- OAuth apps run in unverified/developer mode; token-based connections work immediately with user-supplied PAT/Bot tokens, while GitHub App OAuth requires installing the app on target repositories in GitHub Settings.
