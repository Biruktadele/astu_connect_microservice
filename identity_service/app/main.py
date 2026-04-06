import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.config import settings
from .infrastructure.database import Base, engine, run_add_column_migrations, SessionLocal
from .infrastructure.models import UserModel
from .infrastructure.messaging import outbox_relay
from .interface.api.endpoints import auth, users, follows, admin

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _seed_initial_admin():
    email = settings.INITIAL_ADMIN_EMAIL
    if not email:
        return
    db = SessionLocal()
    try:
        m = db.query(UserModel).filter(UserModel.email == email).first()
        if not m:
            logger.info("INITIAL_ADMIN_EMAIL=%s — user not found yet; will promote on next startup after registration", email)
            return
        roles = m.roles if m.roles else ["student"]
        if "admin" not in roles:
            roles.append("admin")
            m.roles = roles
            db.commit()
            logger.info("Promoted user %s (%s) to admin", m.username, email)
        else:
            logger.info("User %s (%s) already has admin role", m.username, email)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_add_column_migrations()
    _seed_initial_admin()
    relay_task = asyncio.create_task(outbox_relay.run_forever())
    yield
    await outbox_relay.stop()
    relay_task.cancel()


app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan,
    docs_url=None if settings.PRODUCTION else "/docs",
    redoc_url=None if settings.PRODUCTION else "/redoc",
    openapi_url=None if settings.PRODUCTION else "/openapi.json",
)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(follows.router, prefix=settings.API_V1_STR)
app.include_router(admin.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
