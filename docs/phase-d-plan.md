# Phase D Plan

Date: 2026-02-19
Status: Complete (milestone set exited on 2026-03-02)

## Scope
Phase D delivers an integration framework plus targeted first integrations while preserving current architecture boundaries and public API stability.

In scope:
- Integration contracts and adapter registry.
- OpenCode adapter implementation.
- Tools contract and one concrete read-only adapter.
- OpenHands adapter implementation + sync command.
- Skills hardening for repo-hosted skills catalog.
- Integration tests and boundary tests.

Out of scope:
- RAG implementation.
- Model tiering/runtime policy engine.
- Broad generic multi-frontend sync orchestration.

## Locked Decisions
- Milestone shape: contracts + first concrete adapters.
- Adapter API: typed dataclasses + Python `Protocol`.
- Delivery strategy: Python API first.
- First concrete integration: OpenCode.
- OpenHands: implemented in Phase D.
- Tools: contracts + one read-only adapter.
- RAG and model tiering: deferred.

## Milestones
### D1: Integration foundation + OpenCode
Status: Complete.
- Added `ai_stack.integrations.core` types/protocol/registry/errors.
- Added `OpenCodeAdapter`.
- Added unit tests for registry and OpenCode behavior.
- Added boundary tests for integration/runtime layer separation.

### D2: Tools contract + reference adapter
Status: Complete.
- Added tools types and `ReadOnlyFilesystemToolAdapter`.
- Added tests for read/list behavior, path traversal rejection, and read-only write denial.

### D3: OpenHands runtime adapter + sync
Status: Complete.
- Added OpenHands runtime adapter:
  - `python_client/src/ai_stack/integrations/adapters/openhands/adapter.py`
  - `python_client/src/ai_stack/integrations/adapters/openhands/types.py`
- Added OpenHands sync frontend:
  - `python_client/src/ai_stack/integrations/frontends/openhands/sync.py`
- Added OpenHands sync CLI command:
  - `sync-openhands-config`

### D4: Docs closure set
Status: Complete.
- Updated `docs/architecture.md` with integration layer and boundary rules.
- Updated `docs/roadmap.md` with Phase D milestone status.
- Added `docs/phase-d-exit-report.md`.
- Added intentional OpenCode sync command surface (`sync-opencode-config`).

### D5: In-repo skills catalog
Status: Complete.
- Added Codex-first skills under `skills/`.
- Added `python_client/tests/test_skills_catalog.py`.
- Added install and validation docs for `skills.sh`.

### D6: Hardening + shared skills model
Status: Complete.
- Expanded skills hardening checks:
  - required sections
  - command snippet presence
  - placeholder token checks
- Added shared skills model and loader:
  - `SharedSkillSpec`
  - `ai_stack.integrations.shared.skills`
- Seeded starter shared catalogs (tools, agents, skills).
- Added OpenHands sync capability flags:
  - `--sync-tools`
  - `--sync-agents`
  - `--sync-skills`
  - `--emit-mcp-json`

### D7: OpenCode managed skills sync reset
Status: Complete.
- Replaced OpenCode `--sync-skills` seed usage with repo-backed managed catalog loader:
  - `ai_stack.integrations.frontends.opencode.skills_catalog`
- Managed sync set:
  - `ai-stack-runtime-setup`
  - `ai-stack-model-operations`
  - `ai-stack-opencode-sync`
  - `find-skills` (vendored pinned snapshot)
- Added maintenance workflow:
  - `docs/skills-refresh.md`

## Core Adapter Lifecycle
1. Build context (`IntegrationContext`) from runtime state.
2. Register adapter(s) in integration registry.
3. Resolve adapter by name.
4. Run `validate(context)`.
5. Build integration config via `build_runtime_config(context)`.
6. Optionally run `smoke_test(context)`.

## Acceptance Criteria
- Integration contracts are typed and stable.
- OpenCode adapter implemented and tested.
- Tools contract + read-only adapter implemented and tested.
- OpenHands adapter and sync command implemented and tested.
- No architecture boundary violations introduced.
- Existing public APIs remain stable (`ai_stack.llm`, existing CLI scripts).

## Exit Decision
- Phase D is complete for its scoped milestone set (D1-D7).
- Deferred items remain explicitly deferred and are not regressions in Phase D delivery.
- See `docs/phase-d-exit-report.md` for closure summary and follow-up direction.

## Risks and Mitigations
- Risk: integration code absorbs orchestration concerns.
  - Mitigation: protocol-first design + module-boundary tests.
- Risk: inconsistent adapter failure surfaces.
  - Mitigation: typed integration errors and typed result contracts.
- Risk: scope creep into RAG/tiering.
  - Mitigation: explicit deferral and milestone gating.

## Sequencing Notes
1. Foundation contracts first.
2. First concrete adapter second (OpenCode).
3. Tools contract/reference adapter third.
4. OpenHands runtime and per-frontend sync commands are implemented (`sync-opencode-config`, `sync-openhands-config`).
5. Generic multi-frontend orchestration remains deferred.
