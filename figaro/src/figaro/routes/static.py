"""Static file serving for SPA."""

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logger = logging.getLogger(__name__)


def setup_static_routes(app: FastAPI, static_dir: str | None) -> None:
    """Configure static file serving if static_dir is set."""
    if not static_dir or not Path(static_dir).exists():
        return

    static_path = Path(static_dir)
    index_path = static_path / "index.html"

    # Mount static assets
    app.mount("/assets", StaticFiles(directory=static_path / "assets"), name="assets")

    # SPA catch-all router - must be added last
    router = APIRouter(tags=["static"])

    @router.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve static files or fallback to index.html for SPA routing."""
        file_path = static_path / full_path
        if file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(index_path)

    app.include_router(router)
    logger.info(f"Serving static files from {static_dir}")
