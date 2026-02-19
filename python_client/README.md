# ai-stack Python Client

Python package for local AI Stack orchestration and CLI commands.

## Install
```bash
pip install -e .
pip install -e ".[dev]"
pip install -e ".[docs]"
```

## Console Scripts
Configured in `python_client/pyproject.toml`:
- `setup-stack = ai_stack.cli:setup_cli`
- `server-start = ai_stack.cli:start_server_cli`
- `server-status = ai_stack.cli:status_cli`
- `server-stop = ai_stack.cli:stop_server_cli`
- `download-model = ai_stack.cli:download_model_cli`
- `check-deps = ai_stack.cli:check_deps_cli`
- `uninstall-stack = ai_stack.cli:uninstall_cli`

## Usage Examples
```bash
setup-stack

# Repo ID input
download-model TheBloke/Llama-2-7B-GGUF --cache-diagnostics

# Hugging Face URL input
download-model https://huggingface.co/TheBloke/Llama-2-7B-GGUF --list --cache-diagnostics

server-start --list
server-start llama-2-7b.q4_k_m.gguf --detach
server-status
server-stop
uninstall-stack --yes
uninstall-stack --yes --models
```

## Package Layout
- `ai_stack/core/`: runtime config + shared errors/exceptions.
- `ai_stack/llama/`: GPU detection, build helpers, server runtime helpers.
- `ai_stack/huggingface/`: HF transport client, resolver, metadata extraction, snapshot cache.
- `ai_stack/models/`: model registry + manifest ownership.
- `ai_stack/stack/`: orchestration manager and HF download orchestration.
- `ai_stack/cli/`: CLI wrappers, command modules, and shared runtime helpers.
- `ai_stack/llm.py`: local LLM client facade for llama.cpp-compatible API.

## Runtime Data
- Manifest: `project_root/models/manifest.json`
- HF cache: `project_root/.ai_stack/huggingface/cache.json`

## Structured Events
- Set `AI_STACK_LOG_EVENTS=1` to enable structured event logs (JSON lines on stderr).
- Default is off, so normal CLI output remains unchanged.

## Progress UX
- `setup-stack` and `download-model` now print stable stage checkpoints like `[1/3] ...` for long-running workflows.
- Long clone/build steps also print heartbeat lines (`... <seconds>s elapsed`) so setup no longer appears stalled.

## Selective Uninstall
- `uninstall-stack` defaults to removing all runtime artifacts.
- Use selectors to remove only specific parts:
  - `--models`
  - `--llama`
  - `--runtime-cache`

## Download Workers
- `AI_STACK_HF_MAX_WORKERS` controls bounded concurrent HF file downloads (default `1`).
- Current concurrency applies to model+mmproj fetches only; manifest writes remain serialized.
- Use `download-model ... --cache-diagnostics` to print cache stats, active workers, and `elapsed_s` for quick throughput comparisons.
