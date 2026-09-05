from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.routes import router as dashboard_router
from app.audit.routes import router as audit_router
from app.auth.routes import router as auth_router
from app.departments.routes import router as departments_router
from app.documents.routes import router as documents_router
from app.folders.routes import router as folders_router
from app.ocr.routes import router as ocr_router
from app.search.routes import router as search_router
from app.users.routes import router as users_router
from app.core.config import get_settings
from app.sharepoint.dependencies import close_sharepoint_client

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_sharepoint_client()


app = FastAPI(
    title="Puma Energy Pakistan — Document Management System",
    version="0.1.0",
    lifespan=lifespan,
)

# Signed, httpOnly session cookie — this IS the "backend's own session" from
# the auth flow. Never set this to a weak/default secret in production.
app.add_middleware(SessionMiddleware, secret_key=settings.APP_SECRET_KEY, same_site="lax", https_only=(settings.APP_ENV != "development"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(departments_router)
app.include_router(users_router)
app.include_router(folders_router)
app.include_router(documents_router)
app.include_router(ocr_router)
app.include_router(search_router)
app.include_router(audit_router)
app.include_router(dashboard_router)


@app.get("/health")
async def health():
    """Unauthenticated liveness check — used by Docker/monitoring, not by users."""
    return {"status": "ok", "env": settings.APP_ENV}
