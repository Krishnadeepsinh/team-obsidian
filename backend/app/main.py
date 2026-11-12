import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.database import init_db
from app.services.ai_engine import ai_engine

from app.api.v1.assistant import router as assistant_router
from app.api.v1.auth import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.decisions import router as decisions_router
from app.api.v1.documents import router as documents_router
from app.api.v1.evidence import router as evidence_router
from app.api.v1.gaps import router as gaps_router
from app.api.v1.graph import router as graph_router
from app.api.v1.handover import router as handover_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.knowledge import router as knowledge_router
from app.api.v1.projects import router as projects_router
from app.api.v1.risks import router as risks_router
from app.api.v1.seed import router as seed_router
from app.api.v1.tasks import router as tasks_router
from app.api.v1.team import router as team_router
from app.api.v1.webhooks import router as webhooks_router
from app.api.v1.workspaces import router as workspaces_router

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("team_obsidian")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("TEAM OBSIDIAN backend initialized (env=%s)", settings.APP_ENV)
    yield


app = FastAPI(
    title="TEAM OBSIDIAN - Knowledge Handover Platform API",
    version=settings.VERSION,
    description="Enterprise API for AI-Powered Knowledge Reconstruction, Evidence Verification, and Handover Dossier Synthesis.",
    lifespan=lifespan,
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin-allow-popups")
    path = request.url.path or ""
    if path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    if path not in ("/docs", "/redoc", "/openapi.json"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.APP_ENV == "production":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.CORS_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept", "Origin"],
)

api_prefix = settings.API_V1_STR
app.include_router(auth_router, prefix=api_prefix)
app.include_router(workspaces_router, prefix=api_prefix)
app.include_router(dashboard_router, prefix=api_prefix)
app.include_router(projects_router, prefix=api_prefix)
app.include_router(knowledge_router, prefix=api_prefix)
app.include_router(graph_router, prefix=api_prefix)
app.include_router(assistant_router, prefix=api_prefix)
app.include_router(decisions_router, prefix=api_prefix)
app.include_router(tasks_router, prefix=api_prefix)
app.include_router(risks_router, prefix=api_prefix)
app.include_router(gaps_router, prefix=api_prefix)
app.include_router(integrations_router, prefix=api_prefix)
app.include_router(documents_router, prefix=api_prefix)
app.include_router(evidence_router, prefix=api_prefix)
app.include_router(handover_router, prefix=api_prefix)
app.include_router(team_router, prefix=api_prefix)
app.include_router(seed_router, prefix=api_prefix)
app.include_router(webhooks_router, prefix=api_prefix)


@app.get("/health")
def healthcheck():
    return {
        "status": "healthy",
        "platform": "TEAM OBSIDIAN",
        "version": settings.VERSION,
        "primary_llm": settings.PRIMARY_LLM,
        "secondary_llm": settings.SECONDARY_LLM,
        "embedding_model": ai_engine.effective_embedding_model,
        "embedding_dimensions": settings.EMBEDDING_DIMENSIONS,
    }


@app.get("/")
def root():
    return {
        "message": "Welcome to TEAM OBSIDIAN - AI-Powered Knowledge Handover Platform API",
        "docs_url": "/docs",
        "health_url": "/health",
    }
