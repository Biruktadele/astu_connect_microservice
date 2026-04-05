import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import settings
from .infrastructure.database import Base, engine, run_add_column_migrations
from .infrastructure.messaging import (
    outbox_relay, fanout_worker, user_event_consumer,
    engagement_worker, community_feed_worker,
)
from .interface.api.endpoints import feed
from .interface.api.endpoints import admin as feed_admin

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    run_add_column_migrations()
    t1 = asyncio.create_task(outbox_relay.run_forever())
    t2 = asyncio.create_task(fanout_worker.run_forever())
    t3 = asyncio.create_task(user_event_consumer.run_forever())
    t4 = asyncio.create_task(engagement_worker.run_forever())
    t5 = asyncio.create_task(community_feed_worker.run_forever())
    yield
    await outbox_relay.stop()
    for t in [t1, t2, t3, t4, t5]:
        t.cancel()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(feed.router, prefix=settings.API_V1_STR)
app.include_router(feed_admin.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
