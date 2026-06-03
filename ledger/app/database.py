"""
Database engine setup for the vault layer.
Reads DATABASE_URL from env → PostgreSQL (persistent, Render-hosted).
Falls back to SQLite in /tmp for local dev only.
Never use SQLite in production — /tmp is ephemeral on Render.
"""
import logging
import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

# --- Connection string resolution ---
_DATABASE_URL = os.environ.get("DATABASE_URL")
if not _DATABASE_URL:
    # Reuse db.py's writable-path probe (handles disk mount + PermissionError).
    # Blind os.makedirs(LEDGER_DATA_DIR) crashes when the disk is not mounted yet.
    from .db import get_data_dir

    _data_dir = get_data_dir()
    _DATABASE_URL = f"sqlite:///{_data_dir}/vault.db"
    logger.warning(
        "DATABASE_URL not set — using ephemeral SQLite at %s. "
        "Set DATABASE_URL to a PostgreSQL connection string for persistence.",
        _data_dir,
    )
else:
    # Render injects postgres:// but SQLAlchemy 2.x requires postgresql://
    if _DATABASE_URL.startswith("postgres://"):
        _DATABASE_URL = _DATABASE_URL.replace("postgres://", "postgresql://", 1)
    logger.info("Using PostgreSQL (persistent) database.")

# --- Engine ---
_connect_args = {}
if _DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(
    _DATABASE_URL,
    connect_args=_connect_args,
    pool_pre_ping=True,
    pool_recycle=300,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes on exit."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_db_health() -> dict:
    """Returns DB connectivity status for /health endpoint."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        url_type = "postgresql" if "postgresql" in _DATABASE_URL else "sqlite"
        return {"ok": True, "db": "connected", "url_type": url_type}
    except Exception as e:
        return {"ok": False, "db": "error", "error": str(e)}
