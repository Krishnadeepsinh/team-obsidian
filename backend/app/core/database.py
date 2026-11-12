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


def init_db() -> None:
    """Initialize schema safely; create missing tables if needed."""
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
