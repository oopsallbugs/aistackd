# Phase C Hardening Plan

## Scope
Phase C focuses on reliability and maintainability of the current local orchestration stack before feature-heavy integrations.

Out of scope for this phase:
- OpenCode/OpenHands/RAG/tools feature implementation.
- Manifest/cache schema redesign.
- Runtime path relocation.

## Epic 1: Structured Logging and Event Taxonomy
### Scope
- Introduce structured event records for setup, build, download, cache, and server lifecycle.
- Define stable event IDs/severity fields for CLI and internal logs.

### Non-goals
- Full external log aggregation stack.
- Breaking CLI message format for normal users.

### Acceptance criteria
- Core lifecycle actions emit consistent event IDs.
- Optional verbose mode prints structured context (repo, revision, model, elapsed time).
- Existing human-readable output remains intact by default.

### Test scenarios
- Unit tests for event payload shape per subsystem.
- CLI tests validating verbose log emission toggles.

### Estimated effort
- M

### Risk
- Medium (touches many command paths).

## Epic 2: Retry/Backoff Policy for Transient Network Operations
### Scope
- Add bounded retry/backoff for transient HF operations (SHA check, snapshot fetch, file download trigger points).
- Classify retryable vs non-retryable failures.

### Non-goals
- Infinite retry loops.
- Retrying deterministic validation errors.

### Acceptance criteria
- Retry policy centralized and reused by HF orchestration paths.
- Retry attempts and final outcome are observable in logs.
- Non-retryable failures fail fast with user-safe errors.

### Test scenarios
- Simulated transient error succeeds after retry.
- Simulated permanent error exits without retry storm.

### Estimated effort
- M

### Risk
- Medium (network edge-case handling).

## Epic 3: Progress Reporting UX for Long-Running Operations
### Scope
- Add clear progress updates for snapshot fetch, model download, and build operations.
- Ensure foreground and detached contexts remain readable.

### Non-goals
- Terminal UI framework integration.
- Complex animated progress bars.

### Acceptance criteria
- Users can see operation stage transitions and completion/failure state.
- Progress output does not break existing scriptability.

### Test scenarios
- CLI output tests for progress checkpoints.
- Failure-path output preserves final actionable message.

### Estimated effort
- S-M

### Risk
- Low.

## Epic 4: Download Performance/Parallelism (Bounded and Safe)
### Scope
- Evaluate and implement safe bounded parallelism where it improves throughput.
- Keep cache and registry writes deterministic.

### Non-goals
- Unbounded concurrent downloads.
- Changing flat `/models` runtime layout.

### Acceptance criteria
- Configurable bounded worker count.
- No manifest/cache corruption under concurrent operations.
- Throughput improvement measurable in representative scenarios.

### Test scenarios
- Parallel download tests with deterministic final manifest state.
- Interruption/retry scenarios with partial artifacts.

### Estimated effort
- M-L

### Risk
- High (concurrency + filesystem interactions).

## Epic 5: Reliability Test Expansion (CLI Matrix and Recovery Flows)
### Scope
- Expand success/failure matrix for setup/download/server commands.
- Add recovery-path tests: stale PID, cache fallback, malformed runtime files.

### Non-goals
- Full end-to-end live network dependency in CI.
- Replacing existing unit-level test style.

### Acceptance criteria
- Critical CLI workflows covered with both happy and failure paths.
- Boundary tests enforce architecture import constraints.
- Regression tests added for every new hardening behavior.

### Test scenarios
- `python -m ai_stack` command dispatch.
- HF transport exception mapping to user-safe errors.
- Registry cleanup/mutation behavior.

### Estimated effort
- M

### Risk
- Medium.

## Epic 6: LLM Placement Follow-Up (`ai_stack.llm` Facade)
### Scope
- Move LLM client implementation to `ai_stack/llama/client.py`.
- Keep `ai_stack/llm.py` as compatibility facade re-exporting existing public symbols.

### Non-goals
- Behavior changes to chat/completion APIs.
- New inference features.

### Acceptance criteria
- `from ai_stack.llm import create_client` remains valid.
- `LLMClient`, `LLMResponse`, `quick_chat` remain API-compatible.
- Tests prove old and new import paths behave identically.

### Test scenarios
- Compatibility import tests.
- Health/chat/props URL behavior tests on relocated implementation.

### Estimated effort
- S

### Risk
- Low.

## Sequencing and Dependencies
1. Epic 1 (logging taxonomy).
Dependency note: establishes shared observability fields used by retry/progress work.
2. Epic 2 (retry/backoff).
Dependency note: should emit Epic 1 event schema.
3. Epic 3 (progress UX).
Dependency note: uses logging/event conventions from Epics 1-2.
4. Epic 5 (reliability test expansion).
Dependency note: add tests as Epics 1-3 land; keep matrix current.
5. Epic 6 (LLM placement follow-up).
Dependency note: execute after test expansion is in place for safe movement.
6. Epic 4 (performance/parallelism).
Dependency note: do after logging/retry/tests are mature, because concurrency raises failure complexity.

## Exit Criteria for Phase C
- Reliability and diagnostics are strong enough that integration work (Phase D) can build on stable operational primitives.
