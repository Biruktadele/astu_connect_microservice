import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import settings
from .infrastructure.cassandra_db import get_cassandra_session
from .infrastructure.messaging import shutdown_producer
from .interface.api.endpoints import chat, websocket

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    get_cassandra_session()
    yield
    await shutdown_producer()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(chat.router, prefix=settings.API_V1_STR)
app.include_router(websocket.router)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
