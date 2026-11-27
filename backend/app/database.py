"""
Database setup and SQLAlchemy base for VANI 2.0 Application Backend.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


def normalize_database_url(url: str) -> str:
    """Normalizes postgres:// URLs (used by Render/Heroku) to postgresql:// for SQLAlchemy 2.x."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def build_engine(database_url: str):
    """Creates a SQLAlchemy engine configured for SQLite (local) or PostgreSQL (production)."""
    normalized = normalize_database_url(database_url)
    if normalized.startswith("sqlite"):
        return create_engine(
            normalized,
            connect_args={"check_same_thread": False},
        )
    return create_engine(
        normalized,
        pool_pre_ping=True,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    )


DATABASE_URL = normalize_database_url(os.getenv("DATABASE_URL", "sqlite:///./vani_platform.db"))

engine = build_engine(DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
