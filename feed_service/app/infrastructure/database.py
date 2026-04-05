import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from ..core.config import settings

logger = logging.getLogger(__name__)
engine = create_engine(settings.FEED_DATABASE_URL, pool_pre_ping=True, pool_size=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_add_column_migrations():
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE posts ADD COLUMN IF NOT EXISTS moderation_status VARCHAR DEFAULT 'approved'"))
            conn.commit()
        logger.info("Feed add-column migrations applied")
    except Exception as e:
        logger.warning("Feed add-column migrations skipped: %s", e)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
