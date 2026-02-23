# OpenHands Adapter Spec (Phase D)

Status: docs/spec only (no runtime implementation in Phase D).

## Required Adapter Contract
Any future OpenHands adapter must implement the integration protocol:
- `name: str`
- `validate(context) -> IntegrationValidationResult`
- `build_runtime_config(context) -> IntegrationRuntimeConfig`
- `smoke_test(context) -> IntegrationSmokeResult`

## Expected Runtime Config Keys
The first OpenHands adapter implementation should emit at least:
- `provider`: adapter/provider identifier
- `llama_base_url`: local llama endpoint base
- `api_base`: OpenAI-compatible `/v1` endpoint
- `model`: selected/default model id
- `workspace_root`: project root path

## Validation Criteria
- Llama endpoint URL must be configured.
- Endpoint health must be reachable.
- Default model expectations must be explicit.
- Workspace root path must exist and be readable.

## Smoke-Test Criteria
- Health probe to local llama endpoint succeeds.
- Lightweight completion/chat probe succeeds using configured model.
- Adapter returns deterministic pass/fail detail string for diagnostics.

## Implementation Checklist (Deferred)
1. Create `python_client/src/ai_stack/integrations/adapters/openhands/adapter.py`.
2. Add typed payloads in `types.py`.
3. Add registry + contract tests.
4. Add mocked smoke tests and failure mapping tests.
5. Add docs examples and handoff notes.
