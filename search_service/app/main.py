import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import settings
from .infrastructure.elasticsearch_client import ensure_connected
from .infrastructure.messaging import search_consumer
from .interface.api.endpoints import search

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_connected()
    consumer_task = asyncio.create_task(search_consumer.run_forever())
    yield
    search_consumer.stop()
    consumer_task.cancel()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(search.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
