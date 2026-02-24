# Contributing

## Architecture Rules
- Keep strict layer boundaries.
- Registry owns manifest state.
- Config owns runtime settings only.
- HuggingFace client is transport only.
- Resolver is file-selection logic only.
- SetupManager orchestrates; it does not absorb transport/registry internals.
- `/models` stays flat in current design.

## Forbidden Regressions
- Do not scrape Hugging Face HTML.
- Do not guess metadata when `model_info(files_metadata=True)` can provide it.
- Do not edit `models/manifest.json` outside `ModelRegistry`.
- Do not add registry logic into resolver or HF transport layers.

## CLI Dependency Injection Boundary
- Command modules should depend on injected callables/protocols, not concrete manager construction.
- Wrapper modules (`ai_stack/cli/*.py`) own wiring/injection.
- If a command needs shared wiring, add helper modules instead of cross-importing command implementations.

## Integration Boundary Rules
- `ai_stack.integrations` is API-first and split by role:
  - `core/` for contracts/registry/errors
  - `adapters/` for runtime adapter implementations
  - `frontends/` for external-client sync/export flows
  - `shared/` for canonical shared assets
- Runtime core layers (`core`, `llama`, `huggingface`, `models`, `stack`) must not import integration modules.
- CLI wrappers may import integration entrypoints for explicit user-triggered sync commands.
- Cross-frontend shared tool/agent assets belong under `ai_stack/integrations/shared/`; frontend adapters map them to target config formats.
- Integration adapters must not import or mutate:
  - `ai_stack.stack.manager`
  - `ai_stack.stack.hf_downloads`
  - `ai_stack.models.registry`
  - `ai_stack.huggingface.*`
- Prefer public facades (`ai_stack.core.config`, `ai_stack.llm`) when integration runtime context is needed.

## Schema Changes
If you modify manifest or cache structure:
1. Increment `schema_version`.
2. Add migration or explicit fallback behavior.
3. Add/adjust tests covering upgrade/mismatch behavior.
4. Update docs (`docs/architecture.md`, `docs/hf-cache-spec.md`, and relevant README sections).

## Docs Sync Requirement
Whenever module layout, command behavior, or architecture boundaries change:
1. Update `docs/roadmap.md` phase status.
2. Update `docs/architecture.md` module map and boundary notes.
3. Update user-facing command examples in `README.md` and `python_client/README.md`.

## Skills Catalog Maintenance
- Repo-hosted skills live under `skills/*/SKILL.md` at repo root.
- Keep every skill frontmatter valid with required keys:
  - `name`
  - `description`
- Keep commands copy-pastable and aligned with current CLI behavior.
- Update relevant skills whenever command semantics change (for example setup, download, sync flows).
- Keep failure triage and boundaries current with architecture rules.
- Validate with `python_client/tests/test_skills_catalog.py` in every PR that changes `skills/`.

## Quality Bar
- Maintain or improve tests for changed behavior.
- Prefer typed dataclasses/protocols for cross-module contracts.
- Keep user-facing errors actionable and concise.
