"""
Test Configuration — Shared DB Fixtures
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Centralizes the test database setup so all test modules
use the same engine and dependency override.
"""

import os

# MUST be set before importing any app modules
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret-key-for-testing-minimum-64-chars-abcdefghijklmnopq")
os.environ.setdefault("DB_ENCRYPTION_KEY", "")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from daily_agents.database.config import Base, get_db
from daily_agents.api.server import app

# ─── Single shared test engine ───────────────────────────────────────

TEST_DB_URL = "sqlite:///file:shared_test_db?mode=memory&cache=shared&uri=true"
TEST_ENGINE = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})


@event.listens_for(TEST_ENGINE, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


TestSession = sessionmaker(bind=TEST_ENGINE, autocommit=False, autoflush=False)


def _override_get_db():
    db = TestSession()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# Apply the override ONCE at conftest load time
app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    """Create fresh tables before each test, drop after."""
    import daily_agents.database.models  # noqa: F401 — ensure all models registered
    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)
