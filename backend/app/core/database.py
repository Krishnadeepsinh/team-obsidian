from typing import Optional
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings


def _normalize_database_url(url: str) -> str:
    """Ensure SQLAlchemy uses psycopg v3 driver for postgres URLs when psycopg2 is absent."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
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
    """Propagate authenticated app user identity to PostgreSQL transaction-local GUC for RLS alignment."""
    if not IS_POSTGRES or not user_id:
        return
    try:
        db.execute(text("SELECT set_config('app.current_user_id', :uid, true)"), {"uid": str(user_id)})
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
        if not IS_SQLITE and "embedding_records" in existing_tables:
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
    import app.models  # noqa: F401 - Ensure all SQLAlchemy models are registered
    if IS_SQLITE:
        Base.metadata.create_all(bind=engine)
    else:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        try:
            Base.metadata.create_all(bind=engine, checkfirst=True)
        except Exception as exc:
            import logging
            logging.getLogger("team_obsidian").warning("Non-fatal Postgres create_all check skipped: %s", exc)
    try:
        _ensure_runtime_columns()
    except Exception as exc:
        import logging
        logging.getLogger("team_obsidian").warning("Non-fatal additive column sync skipped: %s", exc)
