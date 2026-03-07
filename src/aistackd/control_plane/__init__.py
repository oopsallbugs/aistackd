"""Control-plane constants and exports."""

OPEN_RESPONSES_BASE_PATH = "/v1"
HEALTH_ENDPOINT = "/health"
MODELS_ENDPOINT = "/v1/models"

from aistackd.control_plane.app import (  # noqa: E402
    ControlPlaneError,
    ControlPlaneServer,
    create_control_plane_server,
    serve_control_plane,
)

__all__ = [
    "ControlPlaneError",
    "ControlPlaneServer",
    "HEALTH_ENDPOINT",
    "MODELS_ENDPOINT",
    "OPEN_RESPONSES_BASE_PATH",
    "create_control_plane_server",
    "serve_control_plane",
]
