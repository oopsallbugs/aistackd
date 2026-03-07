# Shared Tools

This directory contains repo-owned baseline tool templates.

Current baseline tools:

- `runtime-status.py`: inspect `health`, `models`, and `admin/runtime`
- `model-admin.py`: search, recommend, install, and activate models through the control plane
- `responses-smoke.py`: prove `/v1/responses` works end to end in streaming or non-streaming mode
- `runtime-wait.py`: poll `health`, `ready`, or a smoke prompt until the host is usable

Frontend sync renders these templates with the active profile's base URL and API key env, then writes managed executable copies into supported frontend-specific tool roots.
