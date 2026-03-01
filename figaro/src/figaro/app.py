"""Figaro orchestrator FastAPI application factory."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from figaro.config import Settings
from figaro.db import create_engine, create_session_factory
from figaro.db.models import Base
from figaro.routes import (
    config_router,
    setup_static_routes,
    websocket_router,
)
from figaro.services import Registry, SchedulerService, TaskManager
from figaro.services.help_request import HelpRequestManager
from figaro.services.nats_service import NatsService

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()

    # Initialize database
    engine: AsyncEngine | None = None
    session_factory = None

    try:
        engine = create_engine(
            settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            echo=settings.db_echo,
            statement_timeout=settings.db_statement_timeout,
            command_timeout=settings.db_command_timeout,
        )
        session_factory = create_session_factory(engine)
        logger.info(
            f"Database connection configured: {settings.database_url.split('@')[-1]}"
        )
    except Exception as e:
        logger.warning(
            f"Failed to configure database, running without persistence: {e}"
        )

    # Initialize core services
    registry = Registry()
    task_manager = TaskManager(session_factory=session_factory)
    scheduler = SchedulerService(
        task_manager, registry, session_factory=session_factory
    )

    # Initialize help request manager
    help_request_manager = HelpRequestManager(
        default_timeout=settings.help_request_timeout,
        session_factory=session_factory,
    )

    # Initialize NATS service
    nats_service = NatsService(
        registry=registry,
        task_manager=task_manager,
        scheduler=scheduler,
        help_request_manager=help_request_manager,
        settings=settings,
        session_factory=session_factory,
    )

    # Wire NatsService into services that need it
    help_request_manager.set_nats_service(nats_service)
    scheduler.set_nats_service(nats_service)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Figaro orchestrator starting up")

        if engine:
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("Database tables created/verified")
                await task_manager.load_pending_tasks()
                await help_request_manager.load_pending_requests()
            except Exception as e:
                logger.error(f"Database initialization error: {e}")

        # Start NATS service
        await nats_service.start()

        await scheduler.start()

        yield

        await scheduler.stop()
        await nats_service.stop()

        if engine:
            await engine.dispose()
            logger.info("Database connection closed")

        logger.info("Figaro orchestrator shutting down")

    orchestrator_app = FastAPI(
        title="Figaro Orchestrator",
        description="NATS-based orchestration system for Claude agents",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Store services in app.state for dependency injection
    orchestrator_app.state.registry = registry
    orchestrator_app.state.task_manager = task_manager
    orchestrator_app.state.scheduler = scheduler
    orchestrator_app.state.help_request_manager = help_request_manager
    orchestrator_app.state.nats_service = nats_service
    orchestrator_app.state.settings = settings

    # Include routers
    orchestrator_app.include_router(websocket_router)
    orchestrator_app.include_router(config_router)

    # Serve static files if configured (must be last - catch-all route)
    setup_static_routes(orchestrator_app, settings.static_dir)

    return orchestrator_app
