"""SQLAlchemy engine and session management."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables if they don't exist. Called on API startup.

    In a larger system this would be replaced by Alembic migrations, but for a
    self-contained service create_all keeps the demo runnable with no extra step.
    """
    from app import models  # noqa: F401  (ensure models are registered)
    Base.metadata.create_all(bind=engine)
