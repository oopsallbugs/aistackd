# AI Stack Architecture

## Layer Rules
| Layer | Responsibility | Must Not Do |
|---|---|---|
| Config (`ai_stack.core.config`) | Runtime settings, path resolution, hardware/runtime detection, summaries | Manifest ownership, HF transport, resolver logic |
| Registry (`ai_stack.models.registry`) | Manifest ownership and local model/mmproj state | Direct HF API access, quant selection policy |
| HuggingFace Client (`ai_stack.huggingface.client`) | Transport (`model_info`, `hf_hub_download`) | File selection, manifest updates |
| Resolver (`ai_stack.huggingface.resolver`) | Decide model/mmproj file from snapshot metadata | API calls, manifest writes |
| Stack Manager (`ai_stack.stack.manager`) | Orchestrate setup/download/server flows | Owning manifest schema, transport details |
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

## CLI DI Boundary
- Rule: command modules should receive dependencies via injected callables/protocols.
- Current state:
  - Enforced for server/setup command modules.
  - `download.py` still combines wrapper + command behavior and directly constructs `SetupManager` (planned Phase C cleanup).

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
