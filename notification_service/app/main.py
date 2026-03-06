import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .core.config import settings
from .infrastructure.database import Base, engine
from .infrastructure.messaging import notification_consumer
from .interface.api.endpoints import notifications

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    consumer_task = asyncio.create_task(notification_consumer.run_forever())
    yield
    notification_consumer.stop()
    consumer_task.cancel()


app = FastAPI(title=settings.PROJECT_NAME, lifespan=lifespan)
app.include_router(notifications.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
