"""Database engine and session management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(
    database_url: str,
    pool_size: int = 20,
    max_overflow: int = 30,
    echo: bool = False,
    statement_timeout: int = 30000,
    command_timeout: int = 30,
) -> AsyncEngine:
    """Create an async SQLAlchemy engine.

    Args:
        database_url: PostgreSQL connection URL (postgresql+asyncpg://...)
        pool_size: Number of connections to keep in the pool
        max_overflow: Maximum overflow connections beyond pool_size
        echo: Whether to log SQL statements
        statement_timeout: PostgreSQL statement timeout in milliseconds
        command_timeout: asyncpg command timeout in seconds

    Returns:
        Configured AsyncEngine instance
    """
    # asyncpg connection arguments for timeouts
    connect_args: dict[str, Any] = {
        "command_timeout": command_timeout,
        "server_settings": {
            "statement_timeout": str(statement_timeout),
        },
    }

    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,  # Verify connections on checkout
        pool_timeout=30,  # Timeout waiting for connection from pool
        echo=echo,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory.

    Args:
        engine: The async engine to use

    Returns:
        Session factory that produces AsyncSession instances
    """
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def get_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    """Get a database session as an async context manager.

    Args:
        session_factory: The session factory to use

    Yields:
        AsyncSession instance

    Example:
        async with get_session(session_factory) as session:
            result = await session.execute(select(TaskModel))
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
