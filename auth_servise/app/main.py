from fastapi import FastAPI
from .api.api import api_router
from .core.config import settings
from .db.session import engine
from .db.base_class import Base

# Create tables in DB (for dev only, prefer migrations later)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

app.include_router(api_router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {"message": "Welcome to ASTU Connect Auth Service", "docs": "/docs"}
