"""
Database Configuration
~~~~~~~~~~~~~~~~~~~~~~
SQLAlchemy engine, session factory, and declarative base.
Supports SQLite for development and PostgreSQL for production.

References:
  - REQ-SCALE-002: SQLite (single-node) and PostgreSQL (prod)
  - REQ-REL-001: Database auto-init on startup
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from daily_agents.config.settings import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy 2.0 models."""
    pass


def _build_engine():
    """Create the SQLAlchemy engine based on current settings."""
    settings = get_settings()
    url = settings.effective_database_url

    connect_args = {}
    if settings.is_sqlite:
        # Enable WAL mode and foreign keys for SQLite
        connect_args["check_same_thread"] = False

    engine = create_engine(
        url,
        connect_args=connect_args,
        echo=settings.debug,
        pool_pre_ping=True,
    )

    # Enable foreign key enforcement for SQLite
    if settings.is_sqlite:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    logger.info("Database engine created: %s", url.split("@")[-1] if "@" in url else url)
    return engine


# Module-level engine and session factory
engine = _build_engine()
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a database session.
    Automatically commits on success, rolls back on error, and closes.
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """
    Create all database tables from the registered models.
    Called on server startup (REQ-REL-001).
    """
    # Import models so they register with Base.metadata
    from daily_agents.database import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    logger.info("✅ Database tables created / verified.")

    # SQLite migration safety check: dynamically add reminder_sent to meetings if missing
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE meetings ADD COLUMN reminder_sent INTEGER DEFAULT 0"))
            logger.info("SQLite database migration applied: added column reminder_sent to meetings table")
    except Exception:
        # Ignore if column already exists or not applicable
        pass

    # SQLite migration safety check: dynamically add conference_provider to projects if missing
    try:
        from sqlalchemy import text
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE projects ADD COLUMN conference_provider TEXT DEFAULT 'manual'"))
            logger.info("SQLite database migration applied: added column conference_provider to projects table")
    except Exception:
        # Ignore if column already exists or not applicable
        pass

