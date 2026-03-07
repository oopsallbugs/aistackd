# aistackd

`aistackd` is a Python-first local AI platform rebuild currently at Phase 0 scaffold plus the first Phase 1 contract slice.

The current repo state provides:

- a `src/aistackd` package skeleton
- a minimal CLI surface for `host`, `client`, `profiles`, `models`, `sync`, and `doctor`
- placeholder modules for runtime, control-plane, frontend sync, models, skills, and state
- shared content roots under `skills/` and `tools/`
- stdlib-only tests and a basic GitHub Actions workflow

## Quickstart

Run the scaffold doctor command:

```bash
PYTHONPATH=src python -m aistackd doctor
```

Run the test suite:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Create and validate a profile:

```bash
PYTHONPATH=src python -m aistackd profiles add local --base-url http://127.0.0.1:8000 --api-key-env AISTACKD_API_KEY --role-hint host --activate
PYTHONPATH=src python -m aistackd profiles validate
PYTHONPATH=src python -m aistackd client
PYTHONPATH=src python -m aistackd sync --target codex --dry-run
```

## Current Scope

The repo is still intentionally thin overall. Model management and frontend writes are still placeholder surfaces, but profile storage, active-profile-derived client config, and sync manifest preview are now implemented.
