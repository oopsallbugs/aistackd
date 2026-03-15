"""Registered CLI command modules."""

from aistackd.cli.commands import client, doctor, frontend, host, models, profiles, sync

COMMAND_MODULES = (host, client, profiles, models, sync, frontend, doctor)

__all__ = ["COMMAND_MODULES"]
