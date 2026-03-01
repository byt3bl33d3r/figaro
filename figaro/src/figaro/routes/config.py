"""Configuration API endpoint for client discovery."""

from fastapi import APIRouter, Request

router = APIRouter(tags=["config"])


@router.get("/api/config")
async def get_config(request: Request) -> dict[str, str]:
    """Return configuration for UI clients (e.g., NATS WS URL)."""
    settings = request.app.state.settings
    return {"nats_ws_url": settings.nats_ws_url}
