"""OpenTelemetry tracing setup for the Figaro orchestrator."""

import os

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine

from figaro_nats import init_tracing as base_init_tracing


def init_tracing(app: FastAPI, engine: AsyncEngine | None = None) -> None:
    """Initialize OpenTelemetry tracing for the orchestrator.

    Calls figaro_nats.init_tracing for the base TracerProvider, then sets up
    auto-instrumentors for FastAPI, SQLAlchemy, and logging when
    OTEL_EXPORTER_OTLP_ENDPOINT is configured.
    """
    base_init_tracing("figaro-orchestrator")

    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return

    FastAPIInstrumentor.instrument_app(app)
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=engine.sync_engine)

    # Inject trace/span IDs into log records for correlation
    LoggingInstrumentor().instrument()
