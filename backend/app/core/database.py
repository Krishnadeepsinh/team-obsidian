from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings


def _normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy uses psycopg v3 driver for postgres URLs and resolves relative SQLite URLs absolutely."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if url in ("sqlite:///./obsidian.db", "sqlite:///obsidian.db"):
        url = f"sqlite:///{settings.DEFAULT_DB_FILE.as_posix()}"
    return url


DATABASE_URL = _normalize_database_url(settings.DATABASE_URL)
IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRES = DATABASE_URL.startswith("postgresql")

connect_args = {"check_same_thread": False} if IS_SQLITE else {}
engine_kwargs = {
    "connect_args": connect_args,
    "echo": False,
}
if IS_POSTGRES:
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 300
    engine_kwargs["pool_size"] = 5
    engine_kwargs["max_overflow"] = 5
    engine_kwargs["pool_timeout"] = 10

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def set_rls_user_context(db: Session, user_id: Optional[str]) -> None:
    """Propagate authenticated app user identity to PostgreSQL session GUC for RLS alignment."""
    if not IS_POSTGRES or not user_id:
        return
    try:
        # Use session-scoped GUC (false) so identity persists across mid-request commits
        db.execute(text("SELECT set_config('app.current_user_id', :uid, false)"), {"uid": str(user_id)})
    except Exception:
        # Avoid breaking requests on dialects/permissions without custom GUC support
        pass


def _ensure_runtime_columns() -> None:
    """Safely add additive columns on existing SQLite/Postgres tables when migrating without downtime."""
    from sqlalchemy import inspect

    insp = inspect(engine)
    existing_tables = set(insp.get_table_names())
    # Keep SQL DDL portable across SQLite and PostgreSQL
    migrations = [
        ("evidences", "parent_evidence_id", "VARCHAR(36)"),
        ("evidences", "chunk_index", "INTEGER DEFAULT 0"),
        ("evidences", "total_chunks", "INTEGER DEFAULT 1"),
        ("evidences", "full_text", "TEXT"),
        ("embedding_records", "parent_id", "VARCHAR(36)"),
        ("embedding_records", "chunk_index", "INTEGER DEFAULT 0"),
        ("embedding_records", "task_type", "VARCHAR(40) DEFAULT 'RETRIEVAL_DOCUMENT'"),
        ("source_records", "extraction_processed_at", "TIMESTAMP"),
        ("password_reset_tokens", "attempts_count", "INTEGER DEFAULT 0"),
        ("password_reset_tokens", "verified_at", "TIMESTAMP"),
        ("password_reset_tokens", "reset_session_token", "VARCHAR(64)"),
    ]
    index_statements = [
        ("source_records", "idx_source_record_project_proc", "project_id, extraction_processed_at"),
        ("embedding_records", "idx_embedding_project_task", "project_id, task_type"),
        ("task_items", "idx_task_project_owner", "project_id, owner"),
        ("exit_interview_questions", "idx_exit_q_handover_status", "handover_id, status"),
        ("pipeline_jobs", "idx_pipeline_job_proj_updated", "project_id, updated_at"),
        ("decisions", "idx_decisions_project_id", "project_id"),
        ("task_items", "idx_task_items_project_id", "project_id"),
        ("dependencies", "idx_dependencies_project_id", "project_id"),
        ("responsibilities", "idx_responsibilities_project_id", "project_id"),
        ("risk_items", "idx_risk_items_project_id", "project_id"),
        ("knowledge_gaps", "idx_knowledge_gaps_project_id", "project_id"),
        ("documents", "idx_documents_project_id", "project_id"),
        ("handovers", "idx_handovers_project_id", "project_id"),
        ("integrations", "idx_integrations_project_id", "project_id"),
        ("activity_logs", "idx_activity_logs_project_id", "project_id"),
        ("activity_logs", "idx_activity_logs_user_id", "user_id"),
        ("notifications", "idx_notifications_user_id", "user_id"),
        ("project_members", "idx_project_members_user_id", "user_id"),
        ("projects", "idx_projects_workspace_id", "workspace_id"),
        ("projects", "idx_projects_creator_id", "creator_id"),
        ("workspaces", "idx_workspaces_owner_id", "owner_id"),
        ("workspaces", "idx_workspaces_org_id", "org_id"),
        ("users", "idx_users_org_id", "org_id"),
        ("handover_sections", "idx_handover_sections_handover_id", "handover_id"),
        ("handover_approvals", "idx_handover_approvals_handover_id", "handover_id"),
        ("handover_versions", "idx_handover_versions_handover_id", "handover_id"),
        ("evidences", "idx_evidences_source_record_id", "source_record_id"),
        ("evidences", "idx_evidences_reviewer_id", "reviewer_id"),
        ("evidence_reviews", "idx_evidence_reviews_evidence_id", "evidence_id"),
        ("evidence_reviews", "idx_evidence_reviews_reviewer_id", "reviewer_id"),
        ("source_records", "idx_source_records_integration_id", "integration_id"),
        ("source_events", "idx_source_events_integration_id", "integration_id"),
        ("documents", "idx_doc_project_sha256", "project_id, sha256_hash"),
        ("knowledge_relationships", "idx_kr_project_rel_type", "project_id, relation_type"),
        ("knowledge_entities", "idx_ke_project_type_name", "project_id, entity_type, name"),
        ("evidences", "idx_ev_project_status", "project_id, verification_status"),
        ("decisions", "idx_decisions_project_date", "project_id, created_at"),
        ("task_items", "idx_tasks_project_status_deadline", "project_id, status, deadline"),
        ("risk_items", "idx_risks_project_status_sev", "project_id, status, severity"),
    ]
    with engine.begin() as conn:
        for table, col, col_type in migrations:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in insp.get_columns(table)}
            if col not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
        for table, idx_name, idx_cols in index_statements:
            if table in existing_tables:
                try:
                    conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({idx_cols})"))
                except Exception:
                    pass
        if not IS_SQLITE:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception:
                pass
            if "embedding_records" in existing_tables:
                try:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS idx_embedding_vector_hnsw "
                            "ON embedding_records USING hnsw (embedding_vector vector_cosine_ops)"
                        )
                    )
                except Exception:
                    pass


def init_db() -> None:
    """Initialize schema safely; create missing tables and additive columns if needed."""
    import logging
    import app.models  # noqa: F401 - Ensure all SQLAlchemy models are registered
    log = logging.getLogger("team_obsidian")

    if IS_SQLITE:
        Base.metadata.create_all(bind=engine)
        try:
            _ensure_runtime_columns()
        except Exception as exc:
            log.warning("Non-fatal additive column sync skipped: %s", exc)
    else:
        try:
            with engine.connect() as conn:
                tables_exist = conn.execute(
                    text("SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'users')")
                ).scalar()
                if not tables_exist:
                    Base.metadata.create_all(bind=engine, checkfirst=True)
                    _ensure_runtime_columns()
        except Exception as exc:
            log.warning("Non-fatal Postgres init check failed, attempting baseline create_all: %s", exc)
            try:
                Base.metadata.create_all(bind=engine, checkfirst=True)
            except Exception as e2:
                log.warning("Non-fatal Postgres create_all check skipped: %s", e2)
