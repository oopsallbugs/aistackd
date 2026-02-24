---
name: ai-stack-model-operations
description: Use this skill to list, select, and download Hugging Face GGUF models with quant preferences and cache diagnostics in ai-stack.
---

# AI Stack Model Operations

## Purpose
Use this skill to operate `download-model` correctly for repo IDs and Hugging Face URLs, including quant selection and diagnostics.

## When To Use
- User needs a new model downloaded.
- User wants to inspect repo files before download.
- User needs cache visibility for HF snapshot behavior.

## Preconditions
- Runtime setup already completed (`setup-stack` successful).
- Working from repository root with active venv.
- Required files are present:
  - `python_client/src/ai_stack/cli/download.py`
  - `python_client/src/ai_stack/stack/hf_downloads.py`
  - `python_client/src/ai_stack/models/registry.py`

## Workflow
1. List available GGUF artifacts before choosing quant:
   - `download-model <namespace/repo> --list --cache-diagnostics`
2. Download with explicit quant preference:
   - `download-model <namespace/repo> --quant Q5_K_M --cache-diagnostics`
3. URL input is also valid:
   - `download-model https://huggingface.co/<namespace/repo> --list`
4. Confirm local model state:
   - `server-start --list`
   - `server-status`

## Failure Triage
- Invalid repo input:
  - use `<namespace/repo>` or full `https://huggingface.co/<namespace/repo>` URL.
- Unexpected quant selection:
  - rerun with explicit `--quant`.
  - inspect resolver behavior paths in `python_client/src/ai_stack/huggingface/resolver.py`.
- Cache confusion:
  - rerun with `--cache-diagnostics` and inspect hit/miss/refresh/fallback output.
- Download errors:
  - retry once; transient network errors use retry logic in `python_client/src/ai_stack/stack/hf_downloads.py`.

## Boundaries
- Do not hand-edit `models/manifest.json`; only `ModelRegistry` mutates it.
- Do not bypass resolver by hardcoding filename guesses.
- Do not add transport logic to resolver or registry modules.
