from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session
from ..core.config import settings

engine = create_engine(settings.GAMIFICATION_DATABASE_URL, pool_pre_ping=True, pool_size=10)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
