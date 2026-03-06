import logging

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from ..core.config import settings

logger = logging.getLogger(__name__)
engine = create_engine(settings.IDENTITY_DATABASE_URL, pool_pre_ping=True, pool_size=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_add_column_migrations():
    """Add new columns to existing users table if missing (e.g. after deploy)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_astu_student BOOLEAN DEFAULT FALSE"))
            conn.commit()
        logger.info("Add-column migrations applied (if any)")
    except Exception as e:
        logger.warning("Add-column migrations skipped or failed: %s", e)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
