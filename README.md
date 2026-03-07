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
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client validate
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd client runtime
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
PYTHONPATH=src python -m aistackd host acquire-backend
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-root /path/to/llama.cpp-prebuilt
PYTHONPATH=src python -m aistackd host acquire-backend --prebuilt-archive /path/to/llama.cpp.tar.gz --source-root /path/to/llama.cpp
PYTHONPATH=src python -m aistackd host acquire-backend --backend-root /path/to/llama.cpp
PYTHONPATH=src AISTACKD_API_KEY=test-key python -m aistackd host validate
PYTHONPATH=src python -m aistackd host
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

## Current Scope

The repo is still intentionally thin overall. Non-streaming function-tool support is now implemented on `POST /v1/responses`, including follow-up `function_call_output` turns through `previous_response_id`, but streaming tool-call events, non-function tools, and broader tool orchestration are still not implemented. Repo-owned operator tools are part of the baseline alongside profile-scoped target model selection, live `llmfit` search/recommend, native `llmfit` TUI browse, managed import of `llmfit`-downloaded GGUFs, direct noninteractive `llmfit` downloads into managed host state with optional quant/budget controls, a managed host-side model store, explicit local GGUF import, common-root local GGUF discovery, controlled Hugging Face CLI fallback including file-URL install, host-side installed/active model state, prerequisite inspection, `llmfit`-backed hardware detection, `llama.cpp` acquisition planning, managed prebuilt install import, managed source-build fallback, adoption of an existing `llama.cpp` installation, local host validation, managed `llama-server` process launch and persisted process state, authenticated `GET /health`, `GET /v1/models`, Responses control-plane endpoints with streaming and non-streaming text generation support, authenticated admin endpoints for runtime inspection plus model search, recommendation, install, and activate, and client-side remote profile validation plus remote model administration are now implemented, alongside active-profile-derived client config, sync planning, OpenCode project-local config writes, Codex project-local provider wiring, baseline skill and tool sync, and ownership manifests.
