# Python Client Audit

## Executive Summary
- `python_client` is in a stronger state after the practical package split: clear layers exist (`core`, `llama`, `huggingface`, `models`, `stack`, `cli`), key boundaries are tested, and CLI behavior is mostly dependency-injected.
- Phase B goals are implemented in code (typed HF snapshot/cache/download results, URL normalization, quant-aware resolver, runtime cache path).
- Remaining risk is concentrated in consistency and maintainability, not feature completeness: large modules, mixed error contracts, and partial DI adoption in CLI download flow.
- Recommended next phase is Phase C hardening with reliability + observability focus before integration-heavy expansion.

## Architecture Compliance Findings
| Issue | Why it matters | Risk | Proposed change | Effort |
|---|---|---|---|---|
| `cli/download.py` still constructs `SetupManager` directly | Keeps one command outside the wrapper-injection pattern used by server/setup command modules; harder to unit-test in isolation | Medium | Split into `download.py` wrapper + `download_run.py` command logic with injected dependencies | M |
| `ai_stack/llm.py` sits at top-level package while runtime server logic lives under `llama/` | Weakens module-map consistency and discoverability for contributors | Low | Move implementation to `ai_stack/llama/client.py`; keep `ai_stack.llm` as compatibility facade | M |
| `core/config.py` does import-time runtime detection via global `config = AiStackConfig()` | Import side effects complicate deterministic testing and alternate runtime wiring | Medium | Introduce lazy/default config factory while preserving `config` for compatibility | M |

## Error Handling Findings
| Issue | Why it matters | Risk | Proposed change | Effort |
|---|---|---|---|---|
| Mixed contracts (`return bool` + print vs typed exceptions) across `llama/build.py`, `llama/server.py`, and orchestration | Makes upstream error handling inconsistent and reduces machine-readable failure reporting | Medium | Standardize internal layer on typed exceptions; keep CLI-facing formatting in `core/errors.py` | M |
| `huggingface/client.py` and download path rely on upstream exceptions without translation at transport boundary | CLI currently covers common validation cases, but non-validation API failures may leak low-level errors | Medium | Map HF transport failures to `DownloadError` with actionable detail at stack boundary | M |
| Status and setup commands print failures but have limited structured diagnostics | Reduces troubleshooting speed for build/network edge cases | Low | Add event codes + optional verbose mode diagnostics in Phase C logging epic | M |

## Type/Interface Findings
| Issue | Why it matters | Risk | Proposed change | Effort |
|---|---|---|---|---|
| Many dict-shaped interfaces (`dict[str, object]`) for config/models/dependency status | Weak static guarantees and easier regression in refactors | Medium | Introduce targeted `TypedDict`/dataclass return types for CLI-facing payloads | M |
| `SetupManager` owns multiple concerns (deps, setup, cache diagnostics, HF orchestration entrypoints) | Larger public surface than needed for focused testing | Low | Extract focused service objects (`DependencyService`, `SetupService`, `HfDownloadService`) while keeping façade | L |
| Protocol-heavy CLI modules are good, but signatures are manually duplicated | Signature drift risk between wrappers and command modules | Low | Consolidate shared protocol definitions in one internal module | S |

## Complexity Hotspots
| Issue | Why it matters | Risk | Proposed change | Effort |
|---|---|---|---|---|
| `python_client/src/ai_stack/models/registry.py` (475 lines) | High surface area for manifest evolution and file-path edge cases | Medium | Split into manifest I/O, model registration, mmproj resolution submodules | L |
| `python_client/src/ai_stack/core/config.py` (361 lines) | Blends config data model, auto-detection, discovery, and summary rendering | Medium | Split into `settings.py`, `runtime_state.py`, `summary.py` (facade retained) | L |
| `python_client/src/ai_stack/stack/hf_downloads.py` (232 lines) | Core orchestration logic and normalization coupled in one file | Medium | Split into `repo_input.py`, `snapshot_cache_flow.py`, `download_flow.py` | M |
| `python_client/src/ai_stack/stack/manager.py` (230 lines) | Manager still broad despite split | Medium | Narrow manager into orchestration facade over dedicated services | M |
| `python_client/src/ai_stack/cli/server_start.py` (246 lines) | Dense UX + process lifecycle logic | Low | Extract argument validation and detached lifecycle reporting helpers | M |

## Test Coverage Gaps
| Issue | Why it matters | Risk | Proposed change | Effort |
|---|---|---|---|---|
| No explicit tests for `python -m ai_stack` command dispatch (`__main__.py`) | Entrypoint drift can break module runner while script entrypoints still pass | Low | Add dispatch tests per command + argv passthrough cases | S |
| Limited negative-path coverage for non-validation HF API failures | Runtime errors may regress into raw stack traces | Medium | Add tests for transport exceptions mapped to user-safe errors | M |
| Registry mutation paths (`remove_model`, `prune_orphan_mmproj`, scan edge cases) lightly covered | Manifest cleanup behavior can drift silently | Medium | Add manifest mutation and recovery matrix tests | M |
| Build/server success-path integration tests are sparse | Hard to detect regressions in command composition and environment flags | Medium | Add mocked end-to-end CLI success-path tests for setup/start/status/stop | M |

## Ranked Backlog (P0–P3)
### P0
- None identified. No blocking architecture violations or data-corruption defects were found in current default flows.

### P1
- Complete CLI DI boundary by extracting download command logic from `cli/download.py`.
- Standardize internal error contracts (typed exceptions inside layers; formatting at CLI boundary).
- Add explicit transport-failure handling tests for HF operations.

### P2
- Move LLM implementation to `ai_stack/llama/client.py` with `ai_stack.llm` facade.
- Reduce module size hotspots (`registry.py`, `core/config.py`, `hf_downloads.py`, `manager.py`, `server_start.py`).
- Add `python -m ai_stack` dispatch tests and registry mutation tests.

### P3
- Tighten type surfaces with targeted `TypedDict`/dataclass outputs.
- Introduce structured event taxonomy for logs and cache/build/server lifecycle diagnostics.

## Recommended Execution Sequence
1. Close DI and error-contract gaps first (highest reliability leverage, low migration risk).
2. Expand reliability tests around CLI/HF failure recovery and module-runner dispatch.
3. Execute focused modularity splits for top hotspots while preserving public imports.
4. Perform LLM relocation (`ai_stack.llm` facade + `ai_stack/llama/client.py` implementation) once test safety net is in place.
5. Finish with typing and logging hardening to support Phase D integrations.
