"""WebSocket endpoints (VNC proxy only, messaging moved to NATS)."""

from fastapi import APIRouter, WebSocket

from figaro.dependencies import RegistryWsDep, SettingsWsDep
from figaro.vnc_proxy import proxy_vnc

router = APIRouter(tags=["websocket"])


@router.websocket("/vnc/{worker_id}")
async def vnc_proxy_endpoint(
    websocket: WebSocket,
    worker_id: str,
    registry: RegistryWsDep,
    settings: SettingsWsDep,
) -> None:
    """Proxy VNC WebSocket connection to a worker.

    Deprecated: Use /guacamole WebSocket via guapy instead. This endpoint
    will be removed in a future release.
    """
    await websocket.accept()
    await proxy_vnc(websocket, worker_id, registry, settings)
