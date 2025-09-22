"""Database configuration for the Harmony backend."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

from app.utils.logging_config import get_logger

logger = get_logger("db")

DATABASE_URL = "sqlite:///./harmony.db"

engine_kwargs: dict[str, object] = {}

if DATABASE_URL.startswith("sqlite"):
    engine_kwargs["connect_args"] = {"check_same_thread": False}

    if DATABASE_URL in {"sqlite://", "sqlite:///:memory:"}:
        engine_kwargs["poolclass"] = StaticPool

engine = create_engine(DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    """Initialise database tables for all registered models."""

    import app.models  # noqa: F401 - ensure core models are registered
    import backend.app.models.plex_models  # noqa: F401 - register Plex models
    import backend.app.models.sync_job  # noqa: F401 - register sync job model
    import backend.app.models.matching_models  # noqa: F401 - register matching models

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
