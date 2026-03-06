# aistackd

`aistackd` is a Python-first local AI platform rebuild currently in Phase 0 scaffolding.

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

## Current Scope

This scaffold is intentionally thin. It establishes naming, package boundaries, and the documented command surface without claiming that runtime, profile, model, or sync behavior is implemented yet.
