import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .core.config import settings
from .infrastructure.database import Base, engine, run_add_column_migrations
from .infrastructure.messaging import outbox_relay
from .interface.api.endpoints import auth, users, follows

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_add_column_migrations()
    relay_task = asyncio.create_task(outbox_relay.run_forever())
    yield
    await outbox_relay.stop()
    relay_task.cancel()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)

app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(users.router, prefix=settings.API_V1_STR)
app.include_router(follows.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
