# AI Stack Roadmap

## Phase Status
| Phase | Status | Focus |
|---|---|---|
| Phase A | Complete | Layered architecture, manifest ownership, HF transport/resolver split |
| Phase B | Complete | HF snapshot cache, quant-aware resolver, metadata derivation, URL normalization |
| Phase C | Complete | Hardening: reliability, observability, UX, and performance |
| Phase D | Active | Integration contracts + first adapters (API-first) |

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

## Phase C (Done)
- Structured logging and event taxonomy across setup/download/server lifecycle.
- Retry/backoff for transient HF operations (`SHA`, snapshot fetch, file download).
- Progress UX checkpoints for long-running setup/download flows.
- Reliability hardening:
  - wrapper-level safe error boundaries for CLI commands
  - recovery-path and compatibility test expansion
- LLM placement cleanup:
  - `ai_stack.llm` remains stable facade
  - implementation moved to `ai_stack/llama/client.py`
- Safe bounded parallelism for download performance:
  - `AI_STACK_HF_MAX_WORKERS` (bounded)
  - deterministic parallel failure ordering
  - serialized registry writes
  - diagnostics visibility (`workers`, `elapsed_s`)

## Phase D (Active, API-First)
Milestone D1 (Complete):
- Integration core contracts added under `ai_stack.integrations.core`:
  - typed context/result dataclasses
  - `IntegrationAdapter` protocol
  - typed integration errors
  - in-memory adapter registry
- OpenCode runtime adapter implemented (`ai_stack.integrations.adapters.opencode.adapter`).
- Integration core + OpenCode tests added.

Milestone D2 (Complete):
- Tools contract and reference read-only filesystem adapter implemented:
  - `ReadOnlyFilesystemToolAdapter`
  - path boundary enforcement and read-only mutation guards
- Tools adapter tests added.

Milestone D3 (Complete):
- OpenHands runtime adapter implemented (`ai_stack.integrations.adapters.openhands.adapter`).
- OpenHands sync frontend implemented (`ai_stack.integrations.frontends.openhands.sync`).
- Added intentional OpenHands sync command surface:
  - `sync-openhands-config`
  - `python -m ai_stack sync-openhands-config`

Milestone D4 (Complete):
- Phase D docs set added/updated:
  - `docs/phase-d-plan.md`
  - `docs/phase-d-exit-report.md` (template)
  - architecture/roadmap updates for integration boundaries.
- Added intentional OpenCode sync command surface:
  - `sync-opencode-config`
  - `python -m ai_stack sync-opencode-config`

Milestone D5 (Complete, Codex-first skills catalog):
- Added in-repo skills catalog at `skills/`:
  - `skills/ai-stack-runtime-setup/SKILL.md`
  - `skills/ai-stack-model-operations/SKILL.md`
  - `skills/ai-stack-opencode-sync/SKILL.md`
- Added static validation tests:
  - `python_client/tests/test_skills_catalog.py`
- Added installation and verification docs for `skills.sh` local usage (`npx skills add ... --agent codex`).

Milestone D6 (Complete, hardening + expansion):
- Skills hardening checks expanded in `python_client/tests/test_skills_catalog.py`:
  - required section enforcement
  - command snippet presence
  - placeholder token rejection
- Added shared skills catalog support:
  - `ai_stack.integrations.shared.skills`
  - `SharedSkillSpec`
- Seeded starter catalogs for tools, agents, and skills.
- Added OpenHands sync capabilities:
  - `--sync-tools`
  - `--sync-agents`
  - `--sync-skills`
  - `--emit-mcp-json`

Milestone D7 (Complete, OpenCode managed skills sync):
- Replaced OpenCode `--sync-skills` source with repo-managed skills catalog loader:
  - `python_client/src/ai_stack/integrations/frontends/opencode/skills_catalog.py`
- Managed OpenCode sync skill set is now:
  - `ai-stack-runtime-setup`
  - `ai-stack-model-operations`
  - `ai-stack-opencode-sync`
  - `find-skills` (vendored pinned snapshot)
- Added refresh workflow documentation:
  - `docs/skills-refresh.md`
- OpenCode sync keeps non-destructive behavior for unrelated user skill folders.

Deferred beyond current Phase D scope:
- RAG implementation.
- Model tiering/runtime policy engine.
- Generic multi-frontend sync orchestration command.

## Non-Negotiable Architecture Rules
- Registry owns manifest.
- HuggingFaceClient is transport only.
- Resolver decides which file to download.
- SetupManager orchestrates.
- Config does not manage model state.
- `/models` directory remains flat.
- Never scrape Hugging Face HTML.
- Never guess metadata without `model_info(files_metadata=True)`.
