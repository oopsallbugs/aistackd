# AI Stack

Local LLM orchestration for `llama.cpp` with Hugging Face model discovery/download.

## What It Does
- Builds and runs `llama.cpp` for local inference.
- Discovers GGUF files from Hugging Face via metadata APIs.
- Selects model files with quant-aware resolver logic.
- Tracks installed models in a manifest registry.
- Caches HF snapshots in local runtime cache.

## Quick Start
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e python_client

setup-stack
download-model Qwen/Qwen2.5-7B-Instruct-GGUF --quant Q5_K_M
download-model https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF --list --cache-diagnostics
server-start qwen2.5-7b-instruct-q5_k_m.gguf
server-status
```

## Commands
- `setup-stack`: dependency check + clone/build `llama.cpp`.
- `download-model`: list/select/download GGUF (+ optional mmproj).
- `server-start`: start model server (foreground or detached).
- `server-status`: show runtime status and model/context info.
- `server-stop`: stop managed detached server.
- `check-deps`: print dependency readiness.
- `uninstall-stack`: remove repo-local runtime artifacts.
- `sync-opencode-config`: intentionally sync global OpenCode config from ai-stack runtime and managed skills.
- `sync-openhands-config`: intentionally sync global OpenHands config from ai-stack runtime.

## Agent Skills (Optional, Codex-First)
This repo now ships a local skills catalog under `skills/` for use with `skills.sh`. https://skills.sh/

Install from repo root:
```bash
npx skills add ./skills/ai-stack-runtime-setup --agent codex
npx skills add ./skills/ai-stack-model-operations --agent codex
npx skills add ./skills/ai-stack-opencode-sync --agent codex
npx skills add ./skills/find-skills --agent codex
```

Install from a repo URL:
```bash
npx skills add <repo_or_path>/skills/ai-stack-runtime-setup --agent codex
```

Manual verification checklist:
1. Confirm skill install location contains the new folders:
   - `ls ~/.codex/skills`
2. Execute one workflow from each installed skill:
   - runtime setup skill: `check-deps` or `setup-stack`
   - model operations skill: `download-model <namespace/repo> --list --cache-diagnostics`
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
- Models and manifest: `./models/`
- HF snapshot cache: `./.ai_stack/huggingface/cache.json`
- Detached server runtime metadata: `./.ai_stack/server/`

## Diagnostics
- Set `AI_STACK_LOG_EVENTS=1` to emit structured JSON event lines to stderr for setup/download/server flows.

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
