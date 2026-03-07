"""Control-plane constants and exports."""

OPEN_RESPONSES_BASE_PATH = "/v1"
HEALTH_ENDPOINT = "/health"
MODELS_ENDPOINT = "/v1/models"
RESPONSES_ENDPOINT = "/v1/responses"
ADMIN_RUNTIME_ENDPOINT = "/admin/runtime"
ADMIN_MODELS_SEARCH_ENDPOINT = "/admin/models/search"
ADMIN_MODELS_RECOMMEND_ENDPOINT = "/admin/models/recommend"
ADMIN_MODELS_INSTALL_ENDPOINT = "/admin/models/install"
ADMIN_MODELS_ACTIVATE_ENDPOINT = "/admin/models/activate"

from aistackd.control_plane.app import (  # noqa: E402
    ControlPlaneError,
    ControlPlaneServer,
    create_control_plane_server,
    serve_control_plane,
)

__all__ = [
    "ADMIN_MODELS_ACTIVATE_ENDPOINT",
    "ADMIN_MODELS_INSTALL_ENDPOINT",
    "ADMIN_MODELS_RECOMMEND_ENDPOINT",
    "ADMIN_MODELS_SEARCH_ENDPOINT",
    "ADMIN_RUNTIME_ENDPOINT",
    "ControlPlaneError",
    "ControlPlaneServer",
    "HEALTH_ENDPOINT",
    "MODELS_ENDPOINT",
    "OPEN_RESPONSES_BASE_PATH",
    "RESPONSES_ENDPOINT",
    "create_control_plane_server",
    "serve_control_plane",
]
