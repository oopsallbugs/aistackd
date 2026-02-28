---
name: find-skills
description: Use this skill to discover additional skills for the current project and install only what is needed.
---

# Find Skills (Pinned Snapshot)

## Purpose
Use this skill to discover project-relevant skills on `skills.sh` and avoid bloating global skill configuration with unrelated entries.

## When To Use
- You start work in a new project and need domain-specific workflows.
- Existing global skills are not enough for the current task.
- You want to install a small targeted set of skills intentionally.

## Preconditions
- `npx` is available in your shell.
- You can access the skills catalog:
  - `https://skills.sh/vercel-labs/skills/find-skills`
- Optional: OpenCode global skills sync has been run:
  - `sync-opencode-config --sync-skills`

## Workflow
1. Inspect the published skill page:
   - `xdg-open https://skills.sh/vercel-labs/skills/find-skills`
2. Install the skill for Codex usage:
   - `npx skills add vercel-labs/skills/find-skills --agent codex`
3. Verify installation:
   - `ls ~/.codex/skills/find-skills`
4. Use the installed skill to discover and shortlist project-relevant skills.

## Failure Triage
- `npx: command not found`:
  - install Node.js/npm first, then retry.
- Install fails due to network:
  - retry on a stable network and verify skills.sh is reachable.
- Skill installed but not recognized:
  - restart the agent host process and re-check `~/.codex/skills/find-skills`.

## Boundaries
- Do not auto-install large bundles of skills globally.
- Prefer project-relevant skills only.
- Keep ai-stack sync behavior explicit (`sync-opencode-config --sync-skills`), not implicit.

## Provenance
- Upstream source: `https://skills.sh/vercel-labs/skills/find-skills`
- Snapshot policy: vendored pinned copy maintained in this repo.
- Snapshot date: `2026-02-28`
