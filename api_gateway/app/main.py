import logging
from pathlib import Path

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core.config import settings
from .interface.api.endpoints import gateway

logging.basicConfig(level=logging.INFO)

# Test web app: in Docker use /app/web (volume); locally use project root / astuconnect_web
WEB_DIR = Path("/app/web") if (Path("/app/web").is_dir()) else (Path(__file__).resolve().parent.parent.parent / "astuconnect_web")
ADMIN_DIR = Path("/app/admin_web") if (Path("/app/admin_web").is_dir()) else (Path(__file__).resolve().parent.parent.parent / "admin_web")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    client = gateway.get_client()
    await client.aclose()


_cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url=None if settings.PRODUCTION else "/docs",
    redoc_url=None if settings.PRODUCTION else "/redoc",
    openapi_url=None if settings.PRODUCTION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(gateway.router)

if WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=str(WEB_DIR), html=True), name="web")

if ADMIN_DIR.is_dir():
    app.mount("/admin", StaticFiles(directory=str(ADMIN_DIR), html=True), name="admin")


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}


@app.get("/")
def root():
    if WEB_DIR.is_dir():
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url="/web/")
    return {"message": "ASTU Connect API Gateway", "docs": "/docs"}
