# OpenHands Adapter Notes (Phase D)

Status: implemented in `adapter.py` and `types.py`; keep this file as behavior notes and future extension checklist.

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

## Follow-up Checklist
1. Expand OpenHands-specific runtime payload coverage as upstream format evolves.
2. Add richer agent/skill mapping scenarios for integration tests.
3. Add docs examples and handoff notes for advanced OpenHands workflows.
