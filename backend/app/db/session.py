"""Database engine and session management.

SQLite is used synchronously and every call from the async application goes
through ``asyncio.to_thread``.  That is simpler and more predictable than an
async SQLite driver, and at the write rate this project produces (a few hundred
rows per second at 10x speed) the bottleneck is fsync, not the driver.

The pragmas below matter: WAL journalling lets the dashboard read history while
the simulation loop is writing, and ``synchronous=NORMAL`` avoids an fsync per
transaction, which is the difference between comfortably keeping up at 10x
speed and falling behind at 2x.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import get_settings
from backend.app.db.models import Base

_settings = get_settings()

engine: Engine = create_engine(
    _settings.database_url,
    echo=False,
    future=True,
    connect_args={"check_same_thread": False},
)

SessionFactory = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@event.listens_for(engine, "connect")
def _configure_sqlite(dbapi_connection, _record) -> None:
    """Apply the pragmas that make concurrent read + write workable."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.execute("PRAGMA cache_size=-32000")  # ~32 MB page cache
    cursor.close()


#: Columns added after the first release: (table, column, SQL definition).
#: ``create_all`` never alters an existing table, so a database created by an
#: older version gets them added here.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("notifications", "read", "BOOLEAN NOT NULL DEFAULT 0"),
)


def init_database() -> None:
    """Create tables if they do not exist yet, and add any newer columns."""
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        for table, column, definition in _ADDED_COLUMNS:
            existing = {
                row[1]
                for row in connection.exec_driver_sql(f"PRAGMA table_info({table})")
            }
            if column not in existing:
                connection.exec_driver_sql(
                    f'ALTER TABLE {table} ADD COLUMN "{column}" {definition}'
                )


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope around a series of operations."""
    session = SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
