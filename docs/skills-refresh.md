# Skills Refresh Guide

## Purpose and Scope
This guide defines how to refresh vendored external skills that are committed under repo root `skills/`.

Current external vendored skill in scope:
- `skills/find-skills/SKILL.md`

This workflow is manual and intentional. Runtime sync commands do not fetch from network.

## Source of Truth
- Upstream page: `https://skills.sh/vercel-labs/skills/find-skills`
- Upstream project: `https://github.com/vercel-labs/skills`
- Local pinned copy used by ai-stack OpenCode sync:
  - `skills/find-skills/SKILL.md`

## Manual Refresh Procedure
1. Review upstream `find-skills` content from official source.
2. Update local vendored file:
   - `skills/find-skills/SKILL.md`
3. Keep frontmatter valid:
   - `name`
   - `description`
4. Update provenance section in file body:
   - upstream URL
   - new snapshot date
   - optional upstream revision/hash if available
5. Ensure content remains compatible with OpenCode global skill layout:
   - `~/.config/opencode/skills/find-skills/SKILL.md`

## Validation Checklist
Run from repo root:
```bash
python3 -m pytest -q python_client/tests/test_skills_catalog.py
python3 -m pytest -q python_client/tests/test_opencode_skills_catalog.py
python3 -m pytest -q python_client/tests/test_integrations_opencode_sync.py
```

Optional end-to-end check:
```bash
sync-opencode-config --sync-skills --dry-run --print
sync-opencode-config --sync-skills
ls ~/.config/opencode/skills/find-skills/SKILL.md
```

## Commit Message Convention
Use a dedicated commit with explicit scope:
```text
skills(find-skills): refresh vendored snapshot
```

Include in commit body:
- upstream source URL
- snapshot date
- short summary of changed guidance

## Rollback Procedure
1. Revert the refresh commit.
2. Re-run validation checks:
   - `python3 -m pytest -q python_client/tests/test_skills_catalog.py`
   - `python3 -m pytest -q python_client/tests/test_opencode_skills_catalog.py`
3. Re-sync global OpenCode skills if needed:
   - `sync-opencode-config --sync-skills`
