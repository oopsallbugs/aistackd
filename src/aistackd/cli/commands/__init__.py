"""Registered CLI command modules."""

from aistackd.cli.commands import client, doctor, host, models, profiles, sync

COMMAND_MODULES = (host, client, profiles, models, sync, doctor)

__all__ = ["COMMAND_MODULES"]
