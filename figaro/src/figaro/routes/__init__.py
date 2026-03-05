from .config import router as config_router
from .guacamole import router as guacamole_router
from .static import setup_static_routes
from .websocket import router as websocket_router

__all__ = [
    "config_router",
    "guacamole_router",
    "setup_static_routes",
    "websocket_router",
]
