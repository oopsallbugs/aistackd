---
name: ai-stack-runtime-setup
description: Use this skill when you need to bootstrap, validate, and run the local ai-stack runtime with setup-stack and server lifecycle commands.
---

# AI Stack Runtime Setup

## Purpose
Use this skill to install prerequisites, build `llama.cpp`, and validate server lifecycle from repo root.

## When To Use
- Fresh machine setup for this repository.
- Rebuild or validate runtime after dependency changes.
- Triage setup or server startup failures.

## Preconditions
- Current working directory is repository root.
- Python virtual environment exists and is activated.
- Package installed in editable mode: `pip install -e python_client`.
- Required files are present:
  - `python_client/src/ai_stack/cli/setup.py`
  - `python_client/src/ai_stack/cli/server.py`
  - `python_client/src/ai_stack/llama/build.py`

## Workflow
1. Verify Python package wiring:
   - `pip install -e python_client`
   - `check-deps`
2. Run full setup:
   - `setup-stack`
3. Validate runtime status:
   - `server-status`
4. Start a model server when a model exists:
   - `server-start --list`
   - `server-start <model-file>.gguf --detach`
   - `server-status`
5. Stop detached server when done:
   - `server-stop`

## Failure Triage
- Build appears stalled:
  - confirm heartbeat logs from `python_client/src/ai_stack/llama/build.py` continue to update elapsed time.
- Setup failure:
  - rerun `check-deps` and inspect missing dependency output.
- Server fails to start:
  - verify model file exists under `models/`.
  - run `server-start --list` to confirm registry-visible model names.
- Port or health failure:
  - run `server-status` and validate configured llama URL from runtime config output.

## Boundaries
- Do not modify manifest directly; registry owns `models/manifest.json`.
- Do not scrape Hugging Face HTML for model metadata.
- Do not add setup logic to CLI wrappers outside orchestrated paths.
