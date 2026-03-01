import logging

import uvicorn

from figaro.app import create_app
from figaro.config import Settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Expose app for Gunicorn: gunicorn figaro:app --worker-class uvicorn.workers.UvicornWorker
app = create_app()


def main() -> None:
    """Debug/development entry point using uvicorn directly."""
    settings = Settings()
    uvicorn.run("figaro:app", host=settings.host, port=settings.port)
