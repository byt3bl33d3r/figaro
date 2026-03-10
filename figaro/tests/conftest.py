"""Pytest configuration and fixtures for figaro tests."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Column, JSON, MetaData, String, Table, event
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from figaro.db.types import EncryptedString
from figaro.services import Registry, TaskManager

SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def _create_sqlite_compatible_metadata():
    """Create a new metadata with SQLite-compatible column types.

    This creates a copy of the models metadata with JSONB replaced by JSON
    and PostgreSQL UUID replaced by String for SQLite compatibility.
    """
    # Import here to avoid circular imports
    from figaro.db.models import Base
    from sqlalchemy import BigInteger, Integer

    new_metadata = MetaData()

    for table_name, table in Base.metadata.tables.items():
        columns = []
        for col in table.columns:
            col_type = col.type
            # Replace PostgreSQL-specific types
            if isinstance(col_type, JSONB):
                col_type = JSON()
            elif isinstance(col_type, PG_UUID):
                col_type = String(36)
            elif isinstance(col_type, EncryptedString):
                col_type = String(255)
            elif col.name == "embedding":
                # Skip the pgvector embedding column — not usable in SQLite
                col_type = String(255)
            elif isinstance(col_type, BigInteger) and col.primary_key:
                # SQLite needs INTEGER for autoincrement PKs
                col_type = Integer()

            # Force autoincrement for primary key integer columns
            autoincrement_value = (
                "auto" if col.primary_key and isinstance(col_type, Integer) else False
            )

            new_col = Column(
                col.name,
                col_type,
                *[c.copy() for c in col.constraints if not c._type_bound],
                primary_key=col.primary_key,
                nullable=col.nullable,
                default=col.default,
                server_default=col.server_default,
                autoincrement=autoincrement_value,
            )
            columns.append(new_col)

        Table(
            table_name,
            new_metadata,
            *columns,
        )

    return new_metadata


@pytest.fixture
async def db_engine():
    """Create an in-memory SQLite database engine for testing."""
    # Use SQLite with aiosqlite for testing
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    # Enable foreign key support for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    @event.listens_for(engine.sync_engine, "connect")
    def register_pgcrypto_stubs(dbapi_connection, connection_record):
        dbapi_connection.create_function(
            "pgp_sym_encrypt",
            2,
            lambda data, key: data.encode() if data else None,
        )
        dbapi_connection.create_function(
            "pgp_sym_decrypt",
            2,
            lambda data, key: data.decode() if isinstance(data, bytes) else data,
        )

    # Create tables using SQLite-compatible metadata
    sqlite_metadata = _create_sqlite_compatible_metadata()

    async with engine.begin() as conn:
        await conn.run_sync(sqlite_metadata.create_all)

    yield engine

    await engine.dispose()


@pytest.fixture
async def db_session(db_engine):
    """Create a database session for testing."""
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def session_factory(db_engine):
    """Create a session factory for testing."""
    return async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
def registry():
    """Create a fresh Registry instance."""
    return Registry()


@pytest.fixture
def task_manager():
    """Create a fresh TaskManager instance."""
    return TaskManager()


@pytest.fixture
def mock_nats_service():
    """Create a mock NatsService."""
    service = MagicMock()
    service.publish_task_assignment = AsyncMock()
    service.publish_supervisor_task = AsyncMock()
    service.broadcast_workers = AsyncMock()
    service.broadcast_supervisors = AsyncMock()
    service.publish_help_response = AsyncMock()
    service.publish_gateway_send = AsyncMock()

    # Mock conn with publish method
    mock_conn = MagicMock()
    mock_conn.publish = AsyncMock()
    mock_conn.is_connected = True
    service.conn = mock_conn

    return service


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom CLI options for live tests."""
    parser.addoption(
        "--record",
        action="store_true",
        default=False,
        help="Record span chain snapshots instead of comparing against them.",
    )


@pytest.fixture
def record_mode(request: pytest.FixtureRequest) -> bool:
    """Return True when --record flag is passed."""
    return request.config.getoption("--record")


def _load_snapshot(name: str) -> list[dict[str, Any]] | None:
    """Load a span chain snapshot from disk, returning None if not found."""
    path = SNAPSHOTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _save_snapshot(name: str, chain: list[dict[str, Any]]) -> None:
    """Save a span chain snapshot to disk."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOTS_DIR / f"{name}.json"
    path.write_text(json.dumps(chain, indent=2) + "\n")


@pytest.fixture
def span_chain_snapshot(request: pytest.FixtureRequest, record_mode: bool) -> Any:
    """Fixture that loads or records span chain snapshots.

    In normal mode, loads the snapshot for the current test and returns it.
    In record mode, returns a callable that saves the snapshot.
    """
    test_name = request.node.name

    class SnapshotHelper:
        def load(self) -> list[dict[str, Any]] | None:
            return _load_snapshot(test_name)

        def save(self, chain: list[dict[str, Any]]) -> None:
            _save_snapshot(test_name, chain)

        @property
        def is_recording(self) -> bool:
            return record_mode

    return SnapshotHelper()
