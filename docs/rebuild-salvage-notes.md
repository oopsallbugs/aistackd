# Rebuild Salvage Notes

Status: Draft
Last updated: 2026-03-07
Purpose: capture concepts worth preserving before deleting the current implementation

## Summary

This document is not a migration plan and not a request to preserve the current architecture.

It records the ideas in the current repo that still align with the new v1 direction:

1. host/client runtime with explicit contracts
2. Open Responses-facing control plane
3. frontend sync with managed baseline content
4. intentional project-local skill discovery
5. testable, resumable operational workflows

Anything not called out here can be treated as safe to delete from a design perspective.

Historical identifiers in this document such as `ai-stack`, `ai_stack`, and `.ai_stack` refer to the deleted implementation only and are not naming guidance for the rebuild.

## 1. Runtime Concepts Worth Keeping

### Structured run state, not ad hoc logs

Worth keeping:

1. per-run directories under `.ai_stack/runtime/runs/<run_id>/`
2. a durable `checkpoint.json`
3. append-only `events.jsonl`
4. a `current_run` pointer for convenience

Why it still fits:

1. host provisioning and service lifecycle will remain long-running and failure-prone
2. resumable operations and inspectable run history still matter in the clean rebuild

Source ideas:

1. `ai-stack-core/src/bootstrap/paths.py`
2. `ai-stack-core/src/bootstrap/checkpoint.py`
3. `ai-stack-core/src/bootstrap/events.py`

### Explicit stage or operation contracts

Worth keeping:

1. stable operation identifiers
2. stable error codes
3. terminal vs retryable failure distinction
4. stage-level outputs that update shared artifacts

Why it still fits:

1. the new repo will still have multi-step host and client workflows
2. operation contracts make CLI behavior, API reporting, and tests much easier to keep consistent

Source ideas:

1. `ai-stack-core/src/bootstrap/contracts.py`
2. `ai-stack-core/src/bootstrap/errors.py`
3. `ai-stack-core/src/bootstrap/runner.py`

### Resume blocked by input fingerprint mismatches

Worth keeping:

1. compute an invocation fingerprint from material inputs
2. block resume when the operator changes the effective request
3. allow resume only from retryable failure points

Why it still fits:

1. this prevents confusing partial reuse when the user changes host mode, profile, model intent, or backend target

Source ideas:

1. `ai-stack-core/src/bootstrap/checkpoint.py`
2. `ai-stack-core/tests/test_checkpoint.py`
3. `ai-stack-core/tests/test_cli.py`

### Append-only artifact updates

Worth keeping:

1. artifacts can be added during a run
2. conflicting overwrites should fail loudly inside a run

Why it still fits:

1. this gives deterministic behavior for discovered host state, acquired binaries, selected models, and synced frontend outputs

Source idea:

1. `ai-stack-core/src/bootstrap/checkpoint.py`

### Atomic writes for stateful files

Worth keeping:

1. atomic write helpers for JSON and text
2. newline-terminated JSON for human-readable state files

Why it still fits:

1. the new repo will persist profiles, manifests, sync ownership state, and runtime state

Source idea:

1. `ai-stack-core/src/bootstrap/io_utils.py`

## 2. Runtime Policy Ideas Worth Keeping

### `llama.cpp` acquisition policy

Worth keeping:

1. treat backend acquisition as a first-class subsystem
2. separate acquisition from runtime serving
3. preserve the `prebuilt first, source fallback` policy from the new plan

Source reference:

1. `ai-stack-core/src/bootstrap/stages/llama_cpp.py`

### Build fallback as a deliberate policy, not hidden behavior

Worth keeping:

1. explicit fallback attempts
2. surfaced remediation hints when hardware/toolchain mismatches occur
3. backend-specific warnings instead of silent retries

Why it still fits:

1. GPU build behavior will remain one of the least reliable parts of the host setup story

Source reference:

1. `ai-stack-core/src/bootstrap/stages/llama_cpp.py`

### Normalize hardware detection into a stable profile

Worth keeping:

1. convert raw `llmfit` output into a deterministic hardware profile
2. derive build flags from normalized hardware state, not directly from raw probe output
3. preserve a warning channel for suspicious host conditions

Why it still fits:

1. this is the correct abstraction boundary between hardware detection and backend acquisition

Source references:

1. `.python_client/src/ai_stack/runtime/hw_mapping.py`
2. `ai-stack-core/src/bootstrap/stages/llama_cpp.py`

### Parse machine output defensively

Worth keeping:

1. tolerate log lines before JSON payloads from helper tools
2. separate raw payload capture from normalized interpretation

Why it still fits:

1. `llmfit` and similar tools may emit mixed human/machine output

Source reference:

1. `.python_client/src/ai_stack/runtime/hw_mapping.py`

### Model selection should preserve local-file workflows

Worth keeping:

1. support explicit local GGUF selection
2. scan common local model roots for discovery
3. treat local models as first-class, not just downloads

Why it still fits:

1. this complements the new `llmfit`-first, Hugging Face-fallback policy and avoids forcing download-only flows

Source reference:

1. `ai-stack-core/src/bootstrap/stages/models.py`

### One active model per running backend

Worth keeping:

1. lifecycle assumes a single actively served model
2. switching models is operationally distinct from listing installed models

Why it still fits:

1. it matches the agreed v1 design and the practical behavior of `llama.cpp`

Source references:

1. `ai-stack-core/src/bootstrap/stages/models.py`
2. `.python_client/src/ai_stack/integrations/adapters/opencode/adapter.py`

## 3. Frontend Sync Concepts Worth Keeping

### Frontend adapters behind a common protocol

Worth keeping:

1. a shared adapter contract
2. per-frontend validation
3. per-frontend runtime config generation
4. per-frontend smoke tests

Why it still fits:

1. Codex and OpenCode remain first-class targets in the new plan
2. this is still the cleanest separation between core state and frontend-specific config shapes

Source references:

1. `.python_client/src/ai_stack/integrations/core/protocols.py`
2. `.python_client/src/ai_stack/integrations/core/types.py`

### Sync should be explicit, previewable, and warning-rich

Worth keeping:

1. explicit sync commands
2. `--dry-run`
3. optional payload printing for inspection
4. warning output separate from hard failure

Why it still fits:

1. this matches the agreed frontend-sync contract and keeps user trust high for global config writes

Source references:

1. `.python_client/src/ai_stack/cli/integrations.py`
2. `README.md`

### Merge managed settings while preserving unrelated config

Worth keeping:

1. update only the provider/model sections owned by the platform
2. preserve unrelated user config keys

Why it still fits:

1. this is central to the new ownership and precedence model

Source reference:

1. `.python_client/src/ai_stack/integrations/adapters/opencode/adapter.py`

### Provider config should be generated from live runtime context

Worth keeping:

1. derive provider base URL from runtime/profile state
2. derive visible models from live runtime knowledge when possible
3. validate the target endpoint before syncing

Why it still fits:

1. this is exactly how the new active-profile sync flow should behave

Source references:

1. `.python_client/src/ai_stack/integrations/adapters/opencode/adapter.py`
2. `.python_client/src/ai_stack/integrations/core/types.py`

## 4. Skill And Catalog Concepts Worth Keeping

### `find-skills` belongs in the baseline

Worth keeping:

1. baseline discovery entry point
2. local-first install guidance
3. explicit multi-frontend install targeting
4. global install only by explicit opt-in

Why it still fits:

1. this exactly matches the agreed baseline-content plan

Source reference:

1. `skills/find-skills/SKILL.md`

### Selective vendoring with provenance

Worth keeping:

1. vendored skills should record upstream source and snapshot date
2. the repo should remain the source of truth for shipped content

Why it still fits:

1. this matches the agreed `reference + selective vendor` policy for `superpowers`, Factory ideas, and external skills

Source reference:

1. `skills/find-skills/SKILL.md`

### Conversation-first planning skills are still useful baseline content

Worth keeping:

1. intent alignment before acting on ambiguous requests
2. decision-complete phase planning and ADR generation
3. evidence tables, assumptions ledgers, and explicit open questions

Why it still fits:

1. these are generic skills that align with the new repo mission
2. they are better candidates for the future baseline catalog than many of the old runtime-specific skills

Source references:

1. `skills/intent-and-context-alignment/SKILL.md`
2. `skills/phase-planning-and-adrs/SKILL.md`

## 5. Test And Validation Ideas Worth Keeping

### Scenario-driven CLI coverage

Worth keeping:

1. tests for fresh runs vs resumed runs
2. tests for explicit run IDs overriding default resume behavior
3. tests for fingerprint mismatch creating a fresh run

Why it still fits:

1. the new host/client CLI will still need the same sort of operator-safe behavior

Source references:

1. `ai-stack-core/tests/test_cli.py`
2. `ai-stack-core/tests/test_checkpoint.py`

### Event sequence continuity across resume

Worth keeping:

1. event sequences should stay monotonic even after process restart or resume

Why it still fits:

1. this keeps operational logs and later UI tooling sane

Source reference:

1. `ai-stack-core/tests/test_events.py`

### Smoke tests should validate externally visible behavior

Worth keeping:

1. probe the health endpoint
2. probe the model-list endpoint
3. keep smoke tests distinct from implementation details

Why it still fits:

1. this maps directly to the new Open Responses control-plane plus repo-owned extensions

Source reference:

1. `ai-stack-core/src/bootstrap/stages/smoke.py`

## 6. Ideas To Preserve Only As Historical Context

These are worth remembering, but not worth reusing directly:

1. the exact old bootstrap stage list
2. old command names such as `bootstrap-stack`, `setup-stack`, or `server-start`
3. the old split between `ai-stack-core` and `.python_client`
4. OpenHands support in v1
5. the old repo framing as either a pure bootstrap system or a pure skill platform

## 7. Recommended Carry-Forward Into The Clean Rebuild

If you keep only a handful of ideas from the old repo, keep these:

1. structured run state with checkpoint plus append-only events
2. input fingerprinting and retryable resume rules
3. normalized hardware profiles derived from raw detection output
4. `llmfit`-first with Hugging Face fallback behind a provider boundary
5. explicit frontend adapters with dry-run sync
6. `find-skills` as a baseline global skill
7. selective vendoring with provenance for adopted external skills

## 8. Files That Were Most Useful For This Salvage Pass

1. `ai-stack-core/src/bootstrap/contracts.py`
2. `ai-stack-core/src/bootstrap/runner.py`
3. `ai-stack-core/src/bootstrap/checkpoint.py`
4. `ai-stack-core/src/bootstrap/events.py`
5. `ai-stack-core/src/bootstrap/stages/llama_cpp.py`
6. `ai-stack-core/src/bootstrap/stages/models.py`
7. `.python_client/src/ai_stack/runtime/hw_mapping.py`
8. `.python_client/src/ai_stack/integrations/core/protocols.py`
9. `.python_client/src/ai_stack/integrations/adapters/opencode/adapter.py`
10. `.python_client/src/ai_stack/cli/integrations.py`
11. `skills/find-skills/SKILL.md`
12. `skills/intent-and-context-alignment/SKILL.md`
13. `skills/phase-planning-and-adrs/SKILL.md`
