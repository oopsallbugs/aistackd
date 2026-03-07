# Shared Tools

This directory contains repo-owned baseline tool templates.

Current baseline tools:

- `runtime-status.py`: inspect `health`, `models`, and `admin/runtime`
- `model-admin.py`: search, recommend, install, and activate models through the control plane
- `responses-smoke.py`: prove `/v1/responses` works end to end in streaming or non-streaming mode
- `runtime-wait.py`: poll `health`, `ready`, or a smoke prompt until the host is usable
- `frontend-smoke.py`: verify this frontend machine can reach the host and complete one non-streaming response
- `tool-call-demo.py`: demonstrate the client-managed function-call loop against `/v1/responses`

Frontend sync renders these templates with the active profile's base URL, model, and API key env, then writes managed executable copies into supported frontend-specific tool roots. These scripts are operator utilities; they are not server-executed repo tools.
