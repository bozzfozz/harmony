from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.utils.logging_config import get_logger

logger = get_logger("db")

DATABASE_URL = "sqlite:///./harmony.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    import app.models  # noqa: F401 - ensures models are registered

    Base.metadata.create_all(bind=engine)
    logger.info("Database initialized")


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
