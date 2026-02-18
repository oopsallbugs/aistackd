"""Typed ai_stack exceptions for consistent boundary handling."""

from __future__ import annotations


class AiStackError(Exception):
    """Base exception for ai_stack domain/runtime errors."""


class ConfigError(AiStackError, ValueError):
    """Configuration or environment validation error."""


class DependencyError(AiStackError, RuntimeError):
    """Missing or invalid runtime dependency."""


class BuildError(AiStackError, RuntimeError):
    """llama.cpp build/setup failure."""


class DownloadError(AiStackError, ValueError):
    """Model download or repository selection failure."""


class ServerError(AiStackError, RuntimeError):
    """Server lifecycle failure (start/stop/status)."""
