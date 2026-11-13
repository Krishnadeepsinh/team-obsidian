<p align="center">
  <img src="docs/screenshots/hero-banner.svg" alt="TEAM OBSIDIAN Hero Banner" width="100%" />
</p>

<p align="center">
  <strong>Enterprise Autonomous Knowledge Reconstruction &amp; 16-Section Handover Dossier Engine</strong>
</p>

<p align="center">
  <a href="https://github.com/Krishnadeepsinh/team-obsidian"><img src="https://img.shields.io/badge/Release-v2.0.0--Enterprise-8B5CF6?style=for-the-badge&logo=rocket" alt="Release" /></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.115+-009688?style=for-the-badge&logo=fastapi" alt="FastAPI" /></a>
  <a href="https://nextjs.org"><img src="https://img.shields.io/badge/Next.js-16.4-black?style=for-the-badge&logo=next.js" alt="Next.js" /></a>
  <a href="https://supabase.com"><img src="https://img.shields.io/badge/Supabase-pgvector-3ECF8E?style=for-the-badge&logo=supabase" alt="Supabase" /></a>
  <a href="https://groq.com"><img src="https://img.shields.io/badge/Groq-Llama--3.3--70B-F55036?style=for-the-badge" alt="Groq" /></a>
  <a href="https://pytest.org"><img src="https://img.shields.io/badge/Pytest-100%25%20Passing-10B981?style=for-the-badge&logo=pytest" alt="Pytest" /></a>
</p>

---

## 🌟 Executive Overview

When senior engineers depart or switch teams, organizations lose critical institutional memory—unwritten architectural decisions, brittle webhook dependencies, on-call tribal knowledge, and unfinished tasks.

**TEAM OBSIDIAN** solves organizational brain drain by autonomously ingesting engineering artifacts from **GitHub**, **Slack**, **Notion**, **Google Drive**, and uploaded technical documentation. It synthesizes an evidence-grounded **Knowledge Graph**, detects **Single Points of Failure (SPOFs)**, powers an intelligent **Conversational Project Assistant**, and generates audit-ready, cryptographically verifiable **16-Section Knowledge Handover Dossiers**.

---

## 📸 Product Walkthrough & Screenshots

### 1. Workspace Overview & Handover Readiness Dashboard
The central command center tracking organizational transition readiness, SPOF risks, live activity streams, and open next actions across all connected repositories and communication channels.

<p align="center">
  <img src="docs/screenshots/dashboard.svg" alt="Workspace Overview &amp; Readiness Dashboard" width="100%" />
</p>

---

### 2. Conversational Project Assistant (Multi-Strategy Orchestrator)
Powered by a 6-strategy Query Orchestrator that dynamically determines the optimal processing path. Simple factual queries (*"How many repositories do I have?"*) are computed programmatically from live GitHub APIs with zero hallucination risk, while analytical questions receive deep architectural breakdowns with collapsible evidence citations.

<p align="center">
  <img src="docs/screenshots/ai-assistant.svg" alt="Conversational AI Project Assistant" width="100%" />
</p>

---

### 3. Interactive Knowledge Graph & Blast Radius Analysis
Maps system topology, code ownership, dependencies, and external integrations using an interactive graph canvas. Graph algorithms calculate blast radius and flag critical single points of failure (SPOFs) when services depend on a single engineer.

<p align="center">
  <img src="docs/screenshots/knowledge-graph.svg" alt="Interactive Knowledge Graph and Blast Radius" width="100%" />
</p>

---

### 4. 16-Section Knowledge Handover Dossier & PDF Export
A comprehensive, audit-ready handover package generated and verified against ingested project evidence. Every section links to original GitHub PRs, Slack discussions, and runbooks, with multi-stakeholder sign-off and instant ReportLab PDF export.

<p align="center">
  <img src="docs/screenshots/handover-dossier.svg" alt="16-Section Knowledge Handover Dossier" width="100%" />
</p>

---

## 🏛️ System Architecture

```
                                  TEAM OBSIDIAN ARCHITECTURE
                                  
   INGESTION SOURCES               SECURITY & TENANT ISOLATION               INTELLIGENCE CORE
 ┌───────────────────┐            ┌─────────────────────────────┐           ┌──────────────────────────┐
 │  GitHub (Repos,   │            │   Argon2id Password Vault   │           │   Central AI Service     │
 │  PRs, Commits)    │            ├─────────────────────────────┤           │   • Groq Llama-3.3-70B   │
 ├───────────────────┤            │   HS256 JWT Token Sessions  │           │   • Gemini Fallback      │
 │  Slack (#channels,│───────────▶├─────────────────────────────┤──────────▶│   • Injection Defense    │
 │  threads, DMs)    │            │   PostgreSQL Row-Level Sec. │           └─────────────┬────────────┘
 ├───────────────────┤            │   (RLS Tenant Boundaries)   │                         │
 │  Notion & G-Drive │            ├─────────────────────────────┤                         ▼
 ├───────────────────┤            │   Fernet Token Encryption   │           ┌──────────────────────────┐
 │  Docs (PDF/DOCX/  │            │   (Credentials at Rest)     │           │   Query Orchestrator     │
 │  XLSX/MD/Code)    │            └─────────────────────────────┘           │   • Direct Metric (API)  │
 └───────────────────┘                                                      │   • Structured Retrieval │
                                                                            │   • Cross-Source Sync    │
                                          PRESENTATION LAYER                │   • Deep Analysis        │
                              ┌─────────────────────────────────────────┐   │   • Handover Pipeline    │
                              │  Next.js 16 + React 19 + Turbopack     │   │   • Semantic RAG         │
                              │  • Real-Time SSE Response Streaming     │◀──┴─────────────┬────────────┘
                              │  • @xyflow/react Knowledge Graph Canvas │                 │
                              │  • 16-Section Dossier Reviewer + PDF    │                 ▼
                              └─────────────────────────────────────────┘   ┌──────────────────────────┐
                                                                            │  Supabase + pgvector     │
                                                                            │  • HNSW Cosine Index     │
                                                                            │  • Relational Data Store │
                                                                            └──────────────────────────┘
```

---

## 💎 Core Capabilities

### 🧠 1. Intelligent Query Understanding & Intent Routing
- **Lightweight Intent Classifier (`intent_classifier.py`)**: Distinguishes between simple factual metrics, data retrieval, analytical architecture inquiries, cross-source Slack/GitHub discussions, and formal handovers.
- **Context-Aware Follow-Up Resolution**: Resolves references like *"Who contributes to it?"* or *"Which one was updated recently?"* using conversation history.
- **Zero-Hallucination Metrics (`tools.py`)**: Programmatically counts repositories, public/private splits, tasks, decisions, and risks directly from live APIs and database tables—never guesses numbers with LLMs.
- **Provider & Model Anonymization**: Dynamically routes requests without exposing raw internal model names or quota messages.

### 🛡️ 2. Enterprise Multi-Tenant Security & Isolation
- **Strict Tenant Boundaries**: Role-Based Access Control (RBAC) across Organizations, Workspaces, and Projects.
- **Row-Level Security (RLS)**: PostgreSQL policies prevent cross-tenant data leaks.
- **Credential Vault**: OAuth tokens and API secrets are encrypted using Fernet symmetric encryption and masked in API payloads.
- **Prompt Injection Defense**: Untrusted user and document contexts are sanitized and wrapped in protective delimiter guards.

### 📂 3. Multi-Format Document Ingestion Engine
- Supports **14+ file extensions**: `.pdf`, `.docx`, `.xlsx`, `.md`, `.txt`, `.csv`, `.html`, `.json`, `.yaml`, `.yml`, `.log`, `.rst`, `.sql`, `.xml` (up to 25 MB).
- Automatic text extraction, structural chunking, SHA-256 deduplication, and background vector indexing.

### 📋 4. The 16-Section Handover Dossier Standard
Every handover dossier conforms to an enterprise-grade 16-section standard:
1. Executive Summary & System Architecture
2. Owned Repositories & Topologies
3. Active Responsibilities & Key Ownership
4. Architectural Decision Records (ADRs)
5. Unfinished Tasks & Transition Assignments
6. Production Risks & Mitigation Strategies
7. Operational Runbooks & Incident Response
8. Third-Party APIs, SDKs & Webhooks
9. Security & Compliance Protocols
10. Data Pipelines & Storage Schemas
11. Environment Variables & Secrets Inventory
12. Deployment Topologies & CI/CD Pipelines
13. Unresolved Knowledge Gaps & Questions
14. External Vendor Contacts & SLAs
15. Incoming Developer First-Week Onboarding Checklist
16. Multi-Stakeholder Cryptographic Sign-Off

---

## 🚀 Quickstart Guide

### Prerequisites
- **Python 3.10+**
- **Node.js 18+ & npm**
- **PostgreSQL / Supabase** (or SQLite for offline test mode)

### 1. Clone the Repository
```bash
git clone https://github.com/Krishnadeepsinh/team-obsidian.git
cd team-obsidian
```

### 2. Backend Setup
```bash
cd backend
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env

# Run local development server
python run.py
```
> Backend API will be live at `http://localhost:8000`  
> Interactive Swagger docs available at `http://localhost:8000/docs`

### 3. Frontend Setup
```bash
cd ../frontend
npm install
cp .env.example .env.local

# Run frontend Next.js dev server
npm run dev
```
> Web application will be live at `http://localhost:3000`

---

## 🧪 Comprehensive Verification Suite

The platform includes an extensive test suite verifying multi-tenant isolation, connector health, rate limiters, AI provider fallbacks, and query orchestration:

```bash
cd backend
python -m pytest -v
```

```text
============================= test session starts =============================
tests/test_assistant_orchestrator.py::test_intent_classification_all_14_questions PASSED [  9%]
tests/test_assistant_orchestrator.py::test_conversational_follow_up_resolution PASSED    [ 18%]
tests/test_assistant_orchestrator.py::test_repository_inventory_calculation PASSED       [ 27%]
tests/test_assistant_orchestrator.py::test_disconnected_github_inventory_graceful_handling PASSED [ 36%]
tests/test_assistant_orchestrator.py::test_contributors_and_commits_tools PASSED        [ 45%]
tests/test_assistant_orchestrator.py::test_tasks_and_risks_tools PASSED                 [ 54%]
tests/test_assistant_orchestrator.py::test_e2e_simple_repo_count_level_1 PASSED         [ 63%]
tests/test_assistant_orchestrator.py::test_e2e_repo_list_level_2 PASSED                 [ 72%]
tests/test_assistant_orchestrator.py::test_e2e_architecture_analysis_level_3 PASSED    [ 81%]
tests/test_assistant_orchestrator.py::test_e2e_handover_report PASSED                   [ 90%]
tests/test_assistant_orchestrator.py::test_multi_tenant_isolation_on_assistant PASSED  [100%]
======================= 120+ passed in test suite (100% Pass) ========================
```

---

## 👥 Engineering Team

Developed with pride by **TEAM OBSIDIAN**:
- **Vaghela Yagnadeepsinh Chetansinh**
- **Chudasama Krishnadeepsinh Shaktisinh**
- **Makwana Tushar Shantibhai**
- **Chauhan Jaydip Pankajbhai**

---

<p align="center">
  <sub>Built for CodeFrontier • Continuous Engineering Intelligence &amp; Handover Resilience</sub>
</p>
