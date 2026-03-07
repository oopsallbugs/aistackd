# aistackd

`aistackd` is a Python-first local AI platform rebuild currently at the scaffold plus Phase 1 contract stage.

The current repo state provides:

- a `src/aistackd` package skeleton
- a minimal CLI surface for `host`, `client`, `profiles`, `models`, `sync`, and `doctor`
- early contract modules for runtime, profiles, host model state, frontend sync, skills, and state
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
PYTHONPATH=src python -m aistackd models recommend
PYTHONPATH=src python -m aistackd models install qwen2.5-coder-7b-instruct-q4-k-m --activate
PYTHONPATH=src python -m aistackd host inspect --backend-root /path/to/llama.cpp
PYTHONPATH=src python -m aistackd host acquire-backend
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-root /path/to/llama.cpp-prebuilt
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-archive /path/to/llama.cpp.tar.gz --source-root /path/to/llama.cpp
PYTHONPATH=src python -m aistackd host acquire-backend --backend-root /path/to/llama.cpp
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host validate
PYTHONPATH=src python -m aistackd host
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host serve
PYTHONPATH=src python -m aistackd sync --target codex --dry-run
PYTHONPATH=src python -m aistackd sync --write
```

## Current Scope

The repo is still intentionally thin overall. Network-backed backend downloads, backend process management, and inference execution are still not implemented, but profile-scoped target model selection, deterministic model-source search/recommendation, host-side installed/active model state, prerequisite inspection, `llmfit`-backed hardware detection, `llama.cpp` acquisition planning, managed prebuilt install import, managed source-build fallback, adoption of an existing `llama.cpp` installation, local host validation, authenticated `GET /health` and `GET /v1/models` control-plane endpoints, active-profile-derived client config, sync planning, OpenCode project-local config writes, Codex project-local provider wiring, baseline skill sync, and ownership manifests are now implemented.
