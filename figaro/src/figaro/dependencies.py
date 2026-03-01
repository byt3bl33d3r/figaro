"""FastAPI dependency injection providers for services."""

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, WebSocket

if TYPE_CHECKING:
    from figaro.services import Registry


# WebSocket-specific dependencies (WebSocket routes don't have Request)
def get_registry_ws(websocket: WebSocket) -> "Registry":
    """Get the registry service from app state (for WebSocket routes)."""
    return websocket.app.state.registry


# WebSocket-specific dependencies
RegistryWsDep = Annotated["Registry", Depends(get_registry_ws)]
