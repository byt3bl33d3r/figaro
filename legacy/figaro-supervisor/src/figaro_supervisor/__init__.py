"""Figaro Supervisor - Task supervisor agent for the Figaro orchestration system."""

import asyncio
import logging

from figaro_supervisor.config import Settings
from figaro_supervisor.supervisor import SupervisorNatsClient, TaskProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def run_heartbeat(client: SupervisorNatsClient, interval: float) -> None:
    """Send periodic liveness heartbeats."""
    # Send first heartbeat immediately so orchestrator confirms presence
    try:
        await client.send_heartbeat()
    except Exception as e:
        logger.warning(f"Initial heartbeat failed: {e}")
    while True:
        await asyncio.sleep(interval)
        try:
            await client.send_heartbeat()
        except Exception as e:
            logger.warning(f"Heartbeat failed (will retry): {e}")


async def run_supervisor() -> None:
    """Run the supervisor service."""
    settings = Settings()
    supervisor_id = settings.get_supervisor_id()

    logger.info(f"Starting supervisor {supervisor_id}")
    logger.info(f"Connecting to NATS at {settings.nats_url}")

    # Create NATS client to orchestrator
    client = SupervisorNatsClient(
        nats_url=settings.nats_url,
        supervisor_id=supervisor_id,
    )

    # Create task processor
    processor = TaskProcessor(
        client=client,
        model=settings.model,
        max_turns=settings.max_turns,
    )

    # Register handlers
    client.on("task", processor.handle_task)

    # Connect to NATS
    connected = await client.connect()
    if not connected:
        logger.error("Failed to connect to NATS, exiting")
        return

    # Build list of tasks to run
    tasks = [
        client.run(),
        run_heartbeat(client, settings.heartbeat_interval),
    ]

    logger.info("Supervisor started")
    try:
        await asyncio.gather(*tasks)
    finally:
        await client.close()


def main() -> None:
    """Entry point for the supervisor service."""
    asyncio.run(run_supervisor())
