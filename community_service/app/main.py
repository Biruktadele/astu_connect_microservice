import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import settings
from .infrastructure.database import Base, engine
from .infrastructure.messaging import outbox_relay
from .interface.api.endpoints import communities
from .interface.api.endpoints import admin as community_admin

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    relay_task = asyncio.create_task(outbox_relay.run_forever())
    yield
    await outbox_relay.stop()
    relay_task.cancel()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(communities.router, prefix=settings.API_V1_STR)
app.include_router(community_admin.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
