# AI Stack

Local LLM orchestration for `llama.cpp` with an `llmfit`-first bootstrap flow.

## What It Does
- Installs a pinned `llmfit` release and detects hardware capability.
- Builds pinned `llama.cpp` from source using mapped backend flags.
- Selects and installs a recommended model via `llmfit`.
- Verifies runtime health and persists bootstrap state for integrations.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e python_client

bootstrap-stack --non-interactive
sync-opencode-config --dry-run --print
sync-openhands-config --dry-run --print
```

## Commands
- `bootstrap-stack`: end-to-end Linux bootstrap (llmfit install, hw detect, llama.cpp build, model install, smoke test, state write).
- `uninstall-stack`: remove repo-local runtime artifacts.
- `sync-opencode-config`: intentionally sync global OpenCode config from ai-stack runtime and managed skills.
- `sync-openhands-config`: intentionally sync global OpenHands config from ai-stack runtime.

## Migration Note
The previous runtime commands were removed in this release:
- `setup-stack`
- `download-model`
- `server-start`
- `server-status`
- `server-stop`
- `check-deps`

Use `bootstrap-stack` for runtime provisioning and keep sync commands for OpenCode/OpenHands integration config export.

## Agent Skills (Optional, Codex examples)
This repo now ships a local skills catalog under `skills/` for use with `skills.sh`. https://skills.sh/

Install from repo root: Codex (or other agents via --agent opencode, --agent openhands etc):
```bash
npx skills add ./skills/ai-stack-runtime-setup --agent codex
npx skills add ./skills/ai-stack-model-operations --agent codex
npx skills add ./skills/ai-stack-opencode-sync --agent codex
npx skills add ./skills/find-skills --agent codex
```

Install project-local for multiple frontends with one command:
```bash
npx skills add ./skills/find-skills --agent codex opencode openhands
```

Optional global install (only if you want user-level skills):
```bash
npx skills add ./skills/find-skills --agent codex -g
```
`-g` is optional and only for global installs.

Install from a repo URL:
```bash
npx skills add <repo_or_path>/skills/ai-stack-runtime-setup --agent codex
```

Manual verification checklist:
1. Confirm skill install location contains the new folders:
   - project-local Codex/OpenCode: `ls ./.agents/skills`
   - project-local OpenHands (if installed): `ls ./.openhands/skills`
   - global `-g` installs only: `ls ~/.codex/skills`
2. Execute one workflow from each installed skill:
   - runtime setup skill: `bootstrap-stack --non-interactive --skip-smoke-test`
   - model operations skill: verify selected model in `.ai_stack/runtime/bootstrap_state.json`
   - opencode sync skill: `sync-opencode-config --sync-tools --sync-agents --sync-skills --dry-run --print`
3. Confirm no runtime behavior changed; these skills are procedural guidance only.

Managed OpenCode skill sync:
- `sync-opencode-config --sync-skills` writes these managed skills to `~/.config/opencode/skills/`:
  - `ai-stack-runtime-setup`
  - `ai-stack-model-operations`
  - `ai-stack-opencode-sync`
  - `find-skills`
- This command can be run from any current working directory as long as `sync-opencode-config` is on your shell `PATH`.
- Unrelated user-installed skill folders are preserved.

## Runtime State Paths
- Bootstrap runtime state: `./.ai_stack/runtime/bootstrap_state.json`
- Managed `llmfit` binary: `./.ai_stack/bin/llmfit`
- Pinned `llama.cpp` checkout/build: `./.ai_stack/llama.cpp/`

## Diagnostics
- Set `AI_STACK_LOG_EVENTS=1` to emit structured JSON event lines to stderr for bootstrap/sync flows.

## Python Module Entry Points
- Config: `ai_stack.core.config`
- Orchestration manager: `ai_stack.stack.manager`
- CLI exports: `ai_stack.cli`
- LLM client facade: `ai_stack.llm`
- Integrations API: `ai_stack.integrations`

## Integrations Layout
- `ai_stack.integrations.core`: contracts, protocol, typed errors, adapter registry.
- `ai_stack.integrations.adapters`: runtime adapter implementations (for example OpenCode and tools).
- `ai_stack.integrations.frontends`: frontend sync/export flows (for example OpenCode config sync).
- `ai_stack.integrations.shared`: canonical shared tool/agent catalogs mapped by frontends.

## Integrations API (Phase D)
Phase D integrations are API-first with explicit sync commands where needed.

```python
from ai_stack.integrations import (
    build_integration_context,
    get_adapter,
    register_default_adapters,
    sync_opencode_global_config,
)

register_default_adapters()
context = build_integration_context()

adapter = get_adapter("opencode")
validation = adapter.validate(context)
runtime = adapter.build_runtime_config(context)
smoke = adapter.smoke_test(context)

# Sync global opencode config intentionally.
result = sync_opencode_global_config(sync_tools=True, sync_agents=True, dry_run=True)
print(result.path)
```

CLI equivalents:
```bash
sync-opencode-config --sync-tools --sync-agents --sync-skills --dry-run --print
sync-openhands-config --sync-tools --sync-agents --sync-skills --dry-run --print --emit-mcp-json
```

Built-in Phase D adapters:
- `opencode`
- `openhands`
- `tools.readonly_filesystem`

## Architecture + Specs
- `docs/architecture.md`
- `docs/roadmap.md`
- `docs/hf-cache-spec.md`
- `docs/resolver-spec.md`
- `docs/phase-d-plan.md`
- `docs/skills-refresh.md`
