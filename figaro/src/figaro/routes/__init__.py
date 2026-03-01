from .config import router as config_router
from .static import setup_static_routes
from .websocket import router as websocket_router

__all__ = [
    "config_router",
    "setup_static_routes",
    "websocket_router",
]
