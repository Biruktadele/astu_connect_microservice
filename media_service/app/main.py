import logging
from fastapi import FastAPI
from .core.config import settings
from .interface.api.endpoints import media

logging.basicConfig(level=logging.INFO)

app = FastAPI(title=settings.PROJECT_NAME)
app.include_router(media.router, prefix=settings.API_V1_STR)


@app.get("/health/live")
def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    return {"status": "ok"}
