import asyncio
import logging

from figaro_worker.config import Settings
from figaro_worker.worker import NatsClient, TaskExecutor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger(__name__)


async def run_heartbeat(client: NatsClient, interval: float) -> None:
    """Send periodic heartbeat messages."""
    # Send first heartbeat immediately so orchestrator confirms presence
    try:
        await client.send_heartbeat()
    except Exception as e:
        logger.warning(f"Initial heartbeat failed: {e}")
    while True:
        await asyncio.sleep(interval)
        await client.send_heartbeat()


async def run_worker() -> None:
    settings = Settings()
    worker_id = settings.get_worker_id()

    logger.info(f"Starting worker {worker_id}")
    logger.info(f"Connecting to NATS at {settings.nats_url}")

    novnc_url = settings.get_novnc_url()
    logger.info(f"VNC URL: {novnc_url}")

    client = NatsClient(
        nats_url=settings.nats_url,
        worker_id=worker_id,
        novnc_url=novnc_url,
    )

    executor = TaskExecutor(client, model=settings.model)
    client.on("task", executor.handle_task)

    connected = await client.connect()
    if not connected:
        logger.error("Failed to connect to NATS, exiting")
        return

    await asyncio.gather(
        client.run(),
        run_heartbeat(client, settings.heartbeat_interval),
    )


def main() -> None:
    asyncio.run(run_worker())
