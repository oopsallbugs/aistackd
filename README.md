# aistackd

`aistackd` is a Python-first local AI platform rebuild with the core host, client, control-plane, and frontend sync path in place.

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
PYTHONPATH=src AISTACKD_REMOTE_API_KEY=test-key python -m aistackd doctor ready --frontend opencode
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
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client validate
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client runtime
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client smoke
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client tool-demo
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client models search qwen
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client models install qwen2.5-coder-7b-instruct-q4-k-m --quant Q4_K_M --budget 16
PYTHONPATH=src python -m aistackd models
PYTHONPATH=src python -m aistackd models set refined-model
PYTHONPATH=src python -m aistackd models search qwen
PYTHONPATH=src python -m aistackd models recommend
PYTHONPATH=src python -m aistackd models browse
PYTHONPATH=src python -m aistackd models import-llmfit
PYTHONPATH=src python -m aistackd models install qwen2.5-coder-7b-instruct-q4-k-m --quant Q4_K_M --budget 16
PYTHONPATH=src python -m aistackd models install qwen2.5-coder-7b-instruct-q4-k-m --gguf-path /path/to/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf --activate
PYTHONPATH=src python -m aistackd models install --hf-url "https://huggingface.co/TeichAI/GLM-4.7-Flash-Claude-Opus-4.5-High-Reasoning-Distill-GGUF?show_file_info=glm-4.7-flash-claude-4.5-opus.q4_k_m.gguf"
PYTHONPATH=src python -m aistackd models install custom-local-model --local-root /path/to/local-models
PYTHONPATH=src python -m aistackd host inspect --backend-root /path/to/llama.cpp
PYTHONPATH=src python -m aistackd host install-llmfit
PYTHONPATH=src python -m aistackd host install-hf
PYTHONPATH=src python -m aistackd host bootstrap
PYTHONPATH=src python -m aistackd host acquire-backend
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-root /path/to/llama.cpp-prebuilt
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-archive /path/to/llama.cpp.tar.gz --source-root /path/to/llama.cpp
PYTHONPATH=src python -m aistackd host acquire-backend --backend-root /path/to/llama.cpp
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host validate
PYTHONPATH=src python -m aistackd host
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host start
PYTHONPATH=src python -m aistackd host stop
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host stop --service
PYTHONPATH=src python -m aistackd host restart
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host restart --service
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host serve
curl -s http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"input":"say hello","stream":false}'
curl -N http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"input":"say hello","stream":true}'
curl -s http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"input":"What models are installed?","tools":[{"type":"function","name":"list_installed_models","description":"Return installed host models.","parameters":{"type":"object","properties":{},"additionalProperties":false}}],"tool_choice":"auto"}'
curl -N http://127.0.0.1:8000/v1/responses \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"input":"What models are installed?","stream":true,"tools":[{"type":"function","name":"list_installed_models","description":"Return installed host models.","parameters":{"type":"object","properties":{},"additionalProperties":false}}],"tool_choice":"auto"}'
curl -s http://127.0.0.1:8000/admin/runtime \
  -H "Authorization: Bearer test-key"
curl -s http://127.0.0.1:8000/admin/models/search \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"query":"glm"}'
curl -s http://127.0.0.1:8000/admin/models/install \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen2.5-coder-7b-instruct-q4-k-m","quant":"Q4_K_M","budget_gb":16}'
curl -s http://127.0.0.1:8000/admin/models/activate \
  -H "Authorization: Bearer test-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"your-model-name"}'
PYTHONPATH=src python -m aistackd sync --target codex --dry-run
PYTHONPATH=src python -m aistackd sync --write
```

When using the current `llmfit` TUI for `models browse`, treat the `Inst` column as the practical provider-compatibility signal. `L` indicates a model that `llmfit` considers installable for `llama.cpp`, so operators should prefer downloading models marked `L`. Even when a specific model cannot be pulled through `llmfit`, the TUI remains the primary discovery and recommendation surface. If `llmfit` model pulling fails, install the GGUF explicitly with:

```bash
PYTHONPATH=src python -m aistackd models install --hf-url "<huggingface-gguf-url>"
```

## Current Scope

The repo is still intentionally thin overall. Function-tool transport is implemented on `POST /v1/responses` for both non-streaming and streaming requests, including follow-up `function_call_output` turns through `previous_response_id`, with persisted host-side response state so tool loops can survive control-plane restarts within the configured retention window. Tool calling is client-managed only: the host transports function calls but does not own or advertise executable repo tools. Synced `tools/` scripts are operator utilities, not model-executed server tools. Non-function tools and broader orchestration are still not implemented. Repo-owned operator tools are part of the baseline alongside profile-scoped target model selection, live `llmfit` search/recommend, native `llmfit` TUI browse, managed import of `llmfit`-downloaded GGUFs, direct noninteractive `llmfit` downloads into managed host state with optional quant/budget controls, a managed host-side model store, explicit local GGUF import, common-root local GGUF discovery, explicit Hugging Face file-URL install when `llmfit` pulling is insufficient, bootstrap-managed `llmfit` and `hf` installs into a user bin directory, `llmfit`-backed hardware detection, remote `llama.cpp` acquisition with pinned prebuilt-first source fallback into repo-managed host state, local host validation, managed `llama-server` process launch plus explicit backend stop/restart controls, managed background control-plane service start/stop/restart, persisted process state with stale-receipt reconciliation after crashes or reboots for both backend and control plane, authenticated `GET /health`, `GET /v1/models`, Responses control-plane endpoints with streaming and non-streaming text generation support, authenticated admin endpoints for runtime inspection plus model search, recommendation, install, and activate, and client-side remote profile validation, smoke, local tool-loop demo, and remote model administration are now implemented, alongside active-profile-derived client config, sync planning, OpenCode project-local config writes, Codex project-local provider wiring, OpenHands CLI/headless config plus microagent sync, baseline skill and tool sync, and ownership manifests. The current roadmap is:

1. broader frontend polish after the OpenHands adapter

The Linux reference-host path is the currently validated path. Broader platform claims should remain conservative until the acceptance matrix expands.

## Live Validation Notes

The current live-tested same-machine Linux flow has already exercised:

- bootstrap-managed `llmfit` and `hf` installs
- source fallback for managed `llama.cpp`
- explicit Hugging Face file-URL install when `llmfit` pulling is insufficient
- `llmfit` browse plus managed GGUF import
- OpenCode sync, readiness checks, and prompt traffic through the control plane

The current default managed backend limits are tuned from that live run:

- `backend_context_size = 24576`
- `backend_predict_limit = 4096`

You can override them when restarting the host:

```bash
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host restart --service --backend-context-size 16384 --backend-predict-limit 2048
```

`aistackd host`, `/health`, and `/admin/runtime` now surface the active backend limits so tuning is visible instead of hidden in the raw backend command.

## Project-Local Skills

Baseline skills shipped by `aistackd sync` remain repo-managed and intentionally small. Project-specific additions are local-first and external/manual in v1.

- For Codex and OpenCode, prefer project-local external installs under `./.agents/skills/` so they stay separate from the managed baseline written into `.codex/skills/` and `.opencode/skills/`.
- For OpenHands, prefer project-local additions under `./.openhands/microagents/`; the synced baseline writes repo-managed microagents there and preserves unmanaged additions.
- Repeated `aistackd sync --write` runs preserve unmanaged project-local skills.
- If you adopt an external skill into the project workflow long-term, you may record provenance beside `SKILL.md` in `aistackd-skill-provenance.json`.
