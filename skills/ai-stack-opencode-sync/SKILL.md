---
name: ai-stack-opencode-sync
description: Use this skill to sync ai-stack OpenCode configuration with dry-run validation and optional shared tools and agents merges.
---

# AI Stack OpenCode Sync

## Purpose
Use this skill to run OpenCode config sync from ai-stack runtime state without introducing implicit auto-sync behavior.

## When To Use
- User needs to refresh global OpenCode config from current ai-stack runtime.
- User wants to merge shared tools or agents into OpenCode config.
- User wants a safe dry-run before writing config changes.

## Preconditions
- ai-stack runtime is installed and available in current environment.
- Working from repository root with active venv.
- Required files are present:
  - `python_client/src/ai_stack/cli/integrations.py`
  - `python_client/src/ai_stack/integrations/frontends/opencode/sync.py`
  - `python_client/src/ai_stack/integrations/frontends/opencode/skills_catalog.py`
  - `python_client/src/ai_stack/integrations/shared/tools/__init__.py`
  - `python_client/src/ai_stack/integrations/shared/agents/__init__.py`

## Workflow
1. Validate and preview output without writing:
   - `sync-opencode-config --sync-tools --sync-agents --sync-skills --dry-run --print`
2. Write merged global config intentionally:
   - `sync-opencode-config --sync-tools --sync-agents --sync-skills`
3. Use custom target when needed:
   - `sync-opencode-config --global-path ~/.config/opencode/opencode.json --sync-skills --dry-run --print`

## Failure Triage
- Invalid existing JSON:
  - resolve JSON syntax in target file, then rerun.
- Validation warnings:
  - inspect warning list and verify runtime context (`llama_url`, default model, endpoint health).
- Missing shared entries:
  - expected behavior if shared catalogs are empty; command reports skip warnings.

## Boundaries
- Keep sync explicit; do not auto-trigger on unrelated commands.
- Do not move sync business logic into CLI wrappers.
- Keep runtime adapters in `integrations/adapters/*` and sync/export logic in `integrations/frontends/*`.
