# aistackd

`aistackd` is a Python-first local AI platform rebuild currently at the scaffold plus Phase 1 contract stage.

The current repo state provides:

- a `src/aistackd` package skeleton
- a minimal CLI surface for `host`, `client`, `profiles`, `models`, `sync`, and `doctor`
- early contract modules for runtime, profiles, models, frontend sync, skills, and state
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
PYTHONPATH=src python -m aistackd profiles add local --base-url http://127.0.0.1:8000 --api-key-env AISTACKD_API_KEY --model local-model --role-hint host --activate
PYTHONPATH=src python -m aistackd profiles validate
PYTHONPATH=src python -m aistackd client
PYTHONPATH=src python -m aistackd models
PYTHONPATH=src python -m aistackd models set refined-model
PYTHONPATH=src python -m aistackd sync --target codex --dry-run
PYTHONPATH=src python -m aistackd sync --write
```

## Current Scope

The repo is still intentionally thin overall. Model acquisition and host-side activation remain placeholder, but profile-scoped model selection, active-profile-derived client config, sync planning, OpenCode project-local config writes, Codex project-local provider wiring, baseline skill sync, and ownership manifests are now implemented.
