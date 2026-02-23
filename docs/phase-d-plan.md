# Phase D Plan

Date: 2026-02-19
Status: Active (current scoped milestone set implemented)

## Scope
Phase D delivers an integration framework plus targeted first integrations while preserving current architecture boundaries and public API stability.

In scope:
- Integration contracts and adapter registry.
- OpenCode adapter implementation.
- Tools contract and one concrete read-only adapter.
- OpenHands adapter spec (docs-only, no runtime code).
- Integration tests and boundary tests.

Out of scope:
- RAG implementation.
- Model tiering/runtime policy engine.
- OpenHands runtime adapter implementation.
- New integration CLI commands (Phase D is Python API-first).

## Locked Decisions
- Milestone shape: contracts + first concrete adapters.
- Adapter API: typed dataclasses + Python `Protocol`.
- Delivery strategy: Python API first.
- First concrete integration: OpenCode.
- OpenHands: docs/spec only in Phase D.
- Tools: contracts + one read-only adapter.
- RAG and model tiering: deferred.

## Milestones
### D1: Integration foundation + OpenCode
Status: In progress.
- Added `ai_stack.integrations.core` types/protocol/registry/errors.
- Added `OpenCodeAdapter`.
- Added unit tests for registry and OpenCode behavior.
- Added boundary tests for integration/runtime layer separation.

### D2: Tools contract + reference adapter
Status: In progress.
- Added tools types and `ReadOnlyFilesystemToolAdapter`.
- Added tests for read/list behavior, path traversal rejection, and read-only write denial.

### D3: OpenHands docs/spec only
Status: In progress.
- Added `python_client/src/ai_stack/integrations/openhands/README.md` with:
  - required contract methods
  - expected runtime config keys
  - validation/smoke criteria
  - implementation checklist

### D4: Docs closure set
Status: Not started
- Updated `docs/architecture.md` with integration layer and boundary rules.
- Updated `docs/roadmap.md` with Phase D milestone status.
- Added `docs/phase-d-exit-report.md` template.

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
- OpenHands has implementation-ready docs spec.
- No architecture boundary violations introduced.
- Existing public APIs remain stable (`ai_stack.llm`, existing CLI scripts).

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
4. OpenHands runtime remains intentionally deferred.
5. CLI integration commands deferred to later phase to keep Phase D API-first.
