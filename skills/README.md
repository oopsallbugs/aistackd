# Shared Skills

This directory contains repo-owned baseline skills.

The current baseline catalog ships:

- `find-skills`

Project-local skills are intentionally separate from this managed baseline in v1.

- Baseline sync owns only the repo-managed skills written into frontend-specific managed roots.
- Project-specific additions should stay local-first and external/manual.
- For Codex and OpenCode, prefer project-local external installs under `./.agents/skills/`.
- For OpenHands, prefer project-local additions under `./.openhands/microagents/`.
- Adopted external skills may record provenance in `aistackd-skill-provenance.json` beside `SKILL.md`.

Example provenance payload:

```json
{
  "schema_version": "v1alpha1",
  "source_type": "skills.sh",
  "source": "vercel-labs/skills/find-skills",
  "installed_via": "manual",
  "snapshot_date": "2026-03-12"
}
```

Repeated `aistackd sync --write` runs must preserve unmanaged project-local additions.
