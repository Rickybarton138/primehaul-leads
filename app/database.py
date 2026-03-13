import logging
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from dotenv import load_dotenv

from app.db_utils import normalize_database_url

load_dotenv()

logger = logging.getLogger("primehaul")

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    logger.critical("DATABASE_URL environment variable is not set")
    # Create a dummy engine that will fail at query time with a clear message
    # rather than crashing the entire app at import time
    engine = None
    SessionLocal = None
else:
    DATABASE_URL = normalize_database_url(DATABASE_URL)

    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    if SessionLocal is None:
        raise RuntimeError(
            "DATABASE_URL is not configured. Set the DATABASE_URL environment variable."
        )
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
