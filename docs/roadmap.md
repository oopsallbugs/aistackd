# AI Stack Roadmap

## Phase Status
| Phase | Status | Focus |
|---|---|---|
| Phase A | Complete | Layered architecture, manifest ownership, HF transport/resolver split |
| Phase B | Complete | HF snapshot cache, quant-aware resolver, metadata derivation, URL normalization |
| Phase C | Active | Hardening: reliability, observability, UX, and performance |
| Phase D | Planned | Integrations: OpenCode/OpenHands/RAG/tools |

## Phase A (Done)
- Manifest introduced and owned by `ModelRegistry`.
- Hugging Face transport client implemented (`model_info(files_metadata=True)` only).
- Resolver implemented for GGUF and mmproj selection.
- Registry integrated into orchestrated download and server flows.
- Legacy mixed-responsibility HF manager removed.

## Phase B (Done)
- HF snapshot cache implemented at `./.ai_stack/huggingface/cache.json`.
- Cache key format implemented as `repo_id@revision`.
- Cache semantics implemented: miss, hit, refresh, fallback.
- Quant parsing and ranked fallback implemented (`DEFAULT_QUANT_RANKING`).
- Explicit `--quant` preference support implemented.
- Hugging Face input normalization implemented for repo IDs and model URLs.
- Derived metadata extraction implemented (`family`, `quant`, `model_size`, `parameter_scale`).
- Typed HF flow results implemented:
  - `SnapshotFetchResult`
  - `HfFileListResult`
  - `HfDownloadResult`

## Phase C (Active)
- Structured logging and event taxonomy across setup/download/server lifecycle.
- Retry/backoff policy for transient network operations.
- Progress UX for long-running operations (snapshot fetch, download, build).
- Safe bounded parallelism for download performance.
- Reliability test expansion:
  - CLI success/failure matrix
  - recovery flows (stale PID, cache fallback, transient failures)
- LLM module placement cleanup:
  - keep `from ai_stack.llm import create_client`
  - move implementation to `ai_stack/llama/client.py`.

## Phase D (Planned)
- OpenCode integration.
- OpenHands integration.
- RAG workflows and tool runtime integration.
- Model tiering/runtime policy.

Note: placeholder directories under `python_client/src` (`opencode`, `openhands`, `rag`, `tools`) are intentional and currently out of active implementation scope.

## Non-Negotiable Architecture Rules
- Registry owns manifest.
- HuggingFaceClient is transport only.
- Resolver decides which file to download.
- SetupManager orchestrates.
- Config does not manage model state.
- `/models` directory remains flat.
- Never scrape Hugging Face HTML.
- Never guess metadata without `model_info(files_metadata=True)`.
