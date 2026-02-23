# AI Stack Architecture

## Layer Rules
| Layer | Responsibility | Must Not Do |
|---|---|---|
| Config (`ai_stack.core.config`) | Runtime settings, path resolution, hardware/runtime detection, summaries | Manifest ownership, HF transport, resolver logic |
| Registry (`ai_stack.models.registry`) | Manifest ownership and local model/mmproj state | Direct HF API access, quant selection policy |
| HuggingFace Client (`ai_stack.huggingface.client`) | Transport (`model_info`, `hf_hub_download`) | File selection, manifest updates |
| Resolver (`ai_stack.huggingface.resolver`) | Decide model/mmproj file from snapshot metadata | API calls, manifest writes |
| Stack Manager (`ai_stack.stack.manager`) | Orchestrate setup/download/server flows | Owning manifest schema, transport details |
| Integrations (`ai_stack.integrations.*`) | Adapter contracts and integration-specific runtime payloads | Manifest/cache ownership, HF transport internals, setup orchestration mutation |
| CLI (`ai_stack.cli`) | Parse args, render UX, call orchestrators | Business logic duplication |

## Runtime Flow
1. CLI wrapper command creates/wires dependencies.
2. `SetupManager` orchestrates operation.
3. HF snapshot fetch path:
   - `HuggingFaceClient.get_repo_sha()` for cache validation
   - cache (`HuggingFaceSnapshotCache`) miss/hit/refresh/fallback decision
   - `HuggingFaceClient.get_snapshot()` as needed
4. Resolver picks model/mmproj from snapshot.
5. Transport downloads selected files.
6. Registry writes manifest entries.

## Integration Flow (Phase D, API-First)
1. Caller builds `IntegrationContext` from runtime state (`ai_stack.integrations.build_integration_context`).
2. Caller registers built-in adapters (`register_default_adapters`) or custom adapters (`register_adapter`).
3. Caller resolves adapter by name (`get_adapter`).
4. Adapter lifecycle:
   - `validate(context)` for readiness checks.
   - `build_runtime_config(context)` for integration payload generation.
   - optional `smoke_test(context)` for lightweight probe verification.
5. Integration layer emits typed results and typed integration errors only; it does not mutate manifest/cache or setup orchestration state.

## Practical Module Map
- `python_client/src/ai_stack/core/`
  - `config.py`: runtime config/data model and discovery
  - `exceptions.py`: typed domain/runtime exceptions
  - `errors.py`: CLI-safe error output helpers
- `python_client/src/ai_stack/llama/`
  - `detect_gpu.py`: hardware detection logic
  - `build.py`: clone/build helpers for llama.cpp
  - `server.py`: start/health-check runtime
- `python_client/src/ai_stack/huggingface/`
  - `client.py`: transport-only HF API wrapper
  - `resolver.py`: quant/mmproj selection
  - `metadata.py`: derived metadata extraction
  - `cache.py`: snapshot cache persistence and schema handling
- `python_client/src/ai_stack/models/`
  - `registry.py`: manifest ownership and local model state
- `python_client/src/ai_stack/stack/`
  - `manager.py`: orchestration facade (`SetupManager`)
  - `hf_downloads.py`: HF download orchestration helpers and typed results
- `python_client/src/ai_stack/cli/`
  - Wrappers: `server.py`, `setup.py`, `download.py`, `__init__.py`
  - Command modules: `server_start.py`, `server_status.py`, `server_stop.py`, `setup_install.py`, `setup_deps.py`, `setup_uninstall.py`
  - Runtime helpers: `server_runtime.py`, shared formatting helpers in `main.py`
- `python_client/src/ai_stack/integrations/`
  - `core/`: integration contracts, protocol, typed errors, adapter registry
  - `opencode/`: first concrete runtime adapter
  - `tools/`: tool adapter contract + read-only filesystem reference adapter
  - `openhands/README.md`: docs-only implementation spec (runtime deferred)

## CLI DI Boundary
- Rule: command modules should receive dependencies via injected callables/protocols.
- Current state:
  - Enforced for server/setup command modules.
  - `download.py` still combines wrapper + command behavior and directly constructs `SetupManager` (planned Phase C cleanup).

## Integration Boundary Rules
- Runtime layers (`core`, `llama`, `huggingface`, `models`, `stack`, `cli`) must not import from `ai_stack.integrations`.
- Integrations must depend on public runtime facades (`ai_stack.core.config`, `ai_stack.llm`) and integration contracts.
- Integrations must not import or mutate:
  - `ai_stack.stack.manager`
  - `ai_stack.stack.hf_downloads`
  - `ai_stack.models.registry`
  - `ai_stack.huggingface.*`
  - CLI modules
- These constraints are enforced with module-boundary tests.

## Typed HF Result Flow
- `SnapshotFetchResult`: snapshot + cache event (`miss`, `hit`, `refresh`, `fallback`).
- `HfFileListResult`: normalized file listing output for `--list`.
- `HfDownloadResult`: selected files, local paths, and error channel for download command.
- Cache event propagation:
  - recorded in `SetupManager._record_cache_event`
  - attached to list/download result
  - rendered in CLI via `format_cache_event`
  - optionally summarized with `--cache-diagnostics`.

## Data Ownership
- Manifest authority: `models/manifest.json` is owned only by `ModelRegistry`.
- HF cache authority: `./.ai_stack/huggingface/cache.json` is owned by `HuggingFaceSnapshotCache`.
- `/models` remains flat by design in current phases.

## Constraints
- Never scrape Hugging Face HTML.
- Never derive file metadata by guessing when `model_info(files_metadata=True)` is available.
- Keep composition over cross-layer merging.
