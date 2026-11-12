import os
import secrets
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Load from backend/.env or current directory
backend_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(backend_root / ".env")
load_dotenv(Path.cwd() / ".env")
load_dotenv(Path.cwd() / "backend" / ".env")


def _parse_cors_origins(raw: str, extra_origin: str = "") -> List[str]:
    origins = [o.strip().rstrip("/") for o in (raw or "").split(",") if o.strip()]
    if extra_origin:
        clean_extra = extra_origin.strip().rstrip("/")
        if clean_extra and clean_extra not in origins:
            origins.append(clean_extra)
    # Never allow wildcard '*' when allow_credentials=True
    filtered = [o for o in origins if o != "*"]
    return filtered or ["http://localhost:3000", "http://127.0.0.1:3000"]


class Settings:
    PROJECT_NAME: str = "TEAM OBSIDIAN"
    VERSION: str = "2.0.0"
    API_V1_STR: str = "/api/v1"

    APP_ENV: str = os.getenv("APP_ENV", "development").lower()
    DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"

    # Database: PostgreSQL (Supabase Session Pooler) in live/staging, SQLite fallback for isolated local dev/tests
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./obsidian.db")

    # AI Engine: Gemini 3.5 Flash / Flash-Lite + local BAAI/bge-small-en-v1.5 embeddings
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    PRIMARY_LLM: str = os.getenv("PRIMARY_LLM", "gemini-3.5-flash")
    SECONDARY_LLM: str = os.getenv("SECONDARY_LLM", "gemini-3.5-flash-lite")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
    EMBEDDING_DIMENSIONS: int = int(os.getenv("EMBEDDING_DIMENSIONS", "384"))

    # Supabase Auth & Storage
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    SUPABASE_SERVICE_ROLE_KEY: str = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    SUPABASE_PROJECT_REF: str = os.getenv("SUPABASE_PROJECT_REF", "")
    SUPABASE_STORAGE_BUCKET: str = os.getenv("SUPABASE_STORAGE_BUCKET", "obsidian-documents")

    # Security: Never allow insecure hardcoded JWT secrets in production
    _raw_secret = os.getenv("SECRET_KEY", "").strip()
    if not _raw_secret:
        if APP_ENV == "production":
            raise RuntimeError("SECRET_KEY environment variable must be set in production.")
        _raw_secret = secrets.token_hex(32)
    SECRET_KEY: str = _raw_secret

    CREDENTIALS_ENCRYPTION_KEY: str = os.getenv("CREDENTIALS_ENCRYPTION_KEY", "").strip()
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", str(60 * 24 * 7)))
    PASSWORD_RESET_EXPIRE_MINUTES: int = int(os.getenv("PASSWORD_RESET_EXPIRE_MINUTES", "30"))

    # Deployment URLs & Restricted CORS (supports localhost + configured production Vercel/custom domains)
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    BACKEND_URL: str = (
        os.getenv("BACKEND_URL", "").strip()
        or os.getenv("RENDER_EXTERNAL_URL", "").strip()
        or "http://localhost:8000"
    ).rstrip("/")
    CORS_ORIGINS: List[str] = _parse_cors_origins(
        os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"),
        extra_origin=FRONTEND_URL,
    )
    CORS_ORIGIN_REGEX: Optional[str] = (
        os.getenv("CORS_ORIGIN_REGEX", "").strip()
        or (r"^https://team-obsidian(-[a-z0-9-]+)?\.vercel\.app$" if APP_ENV == "production" else None)
    )

    # OAuth Apps & Tokens (GitHub, Slack, Notion)
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    SLACK_CLIENT_ID: str = os.getenv("SLACK_CLIENT_ID", "")
    SLACK_CLIENT_SECRET: str = os.getenv("SLACK_CLIENT_SECRET", "")
    SLACK_BOT_TOKEN: str = os.getenv("SLACK_BOT_TOKEN", "")

    NOTION_CLIENT_ID: str = os.getenv("NOTION_CLIENT_ID", "")
    NOTION_CLIENT_SECRET: str = os.getenv("NOTION_CLIENT_SECRET", "")
    NOTION_API_KEY: str = os.getenv("NOTION_API_KEY", "")

    ATLASSIAN_CLIENT_ID: str = os.getenv("ATLASSIAN_CLIENT_ID", "")
    ATLASSIAN_CLIENT_SECRET: str = os.getenv("ATLASSIAN_CLIENT_SECRET", "")
    JIRA_CLIENT_ID: str = os.getenv("JIRA_CLIENT_ID", "")
    JIRA_CLIENT_SECRET: str = os.getenv("JIRA_CLIENT_SECRET", "")
    JIRA_API_TOKEN: str = os.getenv("JIRA_API_TOKEN", "")
    JIRA_EMAIL: str = os.getenv("JIRA_EMAIL", "")
    CONFLUENCE_CLIENT_ID: str = os.getenv("CONFLUENCE_CLIENT_ID", "")
    CONFLUENCE_CLIENT_SECRET: str = os.getenv("CONFLUENCE_CLIENT_SECRET", "")
    CONFLUENCE_API_TOKEN: str = os.getenv("CONFLUENCE_API_TOKEN", "")
    CONFLUENCE_EMAIL: str = os.getenv("CONFLUENCE_EMAIL", "")

    LINEAR_CLIENT_ID: str = os.getenv("LINEAR_CLIENT_ID", "")
    LINEAR_CLIENT_SECRET: str = os.getenv("LINEAR_CLIENT_SECRET", "")
    LINEAR_API_TOKEN: str = os.getenv("LINEAR_API_TOKEN", "")

    GITLAB_CLIENT_ID: str = os.getenv("GITLAB_CLIENT_ID", "")
    GITLAB_CLIENT_SECRET: str = os.getenv("GITLAB_CLIENT_SECRET", "")
    GITLAB_TOKEN: str = os.getenv("GITLAB_TOKEN", "")

    SENTRY_CLIENT_ID: str = os.getenv("SENTRY_CLIENT_ID", "")
    SENTRY_CLIENT_SECRET: str = os.getenv("SENTRY_CLIENT_SECRET", "")
    SENTRY_AUTH_TOKEN: str = os.getenv("SENTRY_AUTH_TOKEN", "")
    SENTRY_ORG_SLUG: str = os.getenv("SENTRY_ORG_SLUG", "")

    # Email Delivery (Password Reset & Invitations)
    RESEND_API_KEY: str = os.getenv("RESEND_API_KEY", "")
    SMTP_HOST: str = os.getenv("SMTP_HOST", "")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USER: str = os.getenv("SMTP_USER", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@teamobsidian.local")

    # Upload Limits
    MAX_UPLOAD_MB: int = int(os.getenv("MAX_UPLOAD_MB", "25"))
    MAX_UPLOAD_BYTES: int = MAX_UPLOAD_MB * 1024 * 1024

    def validate_production_readiness(self) -> None:
        if self.APP_ENV == "production":
            if len(self.SECRET_KEY) < 32 or "change-in-prod" in self.SECRET_KEY:
                raise RuntimeError("Insecure SECRET_KEY configured for production.")
            if not self.CREDENTIALS_ENCRYPTION_KEY:
                raise RuntimeError("CREDENTIALS_ENCRYPTION_KEY must be configured in production.")


settings = Settings()
settings.validate_production_readiness()
