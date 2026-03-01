"""Pytest configuration and fixtures for figaro tests."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import event, JSON, MetaData, Table, Column
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy import String

from figaro.services import Registry, TaskManager


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
