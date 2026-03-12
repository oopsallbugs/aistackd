# Frontend Sync And Baseline Content Plan

Status: Draft
Last updated: 2026-03-06
Companion to: `docs/bootstrap-implementation-plan.md`
Supersedes: prior skills-only platform plan

## 1. Purpose

This document defines the frontend integration slice of the v1 product.

Naming conventions for all new implementation work are defined in `docs/naming-conventions.md`.

The repo is not a pure skill platform. Frontend sync exists to make the runtime plane usable from supported agent frontends with minimal extra operator work.

For v1, frontend sync covers:

1. provider configuration for the active backend profile
2. baseline shared skills
3. baseline shared tools
4. project-local discovery of additional skills through `find-skills`

Canonical baseline agents are deferred.

## 2. V1 Frontend Targets

First-class targets:

1. Codex
2. OpenCode
3. OpenHands

Deferred targets:

1. any additional agent frontend

The roadmap order after the OpenHands adapter is:

1. broader frontend polish

## 3. Product Boundaries

### In Scope

1. frontend adapters for supported targets
2. managed ownership of synced content
3. dry-run and write flows
4. idempotent sync behavior
5. preservation of unmanaged user config and user-installed content
6. baseline content catalogs

### Out Of Scope

1. background auto-sync
2. full catalog package-management semantics
3. global installation of large third-party skill bundles by default
4. canonical baseline agents

## 4. Baseline Content Model

### Skills

The baseline skill set should stay intentionally small and generic.

Initial categories:

1. planning and design support
2. implementation or review support
3. operator/runtime usage support
4. discovery support through `find-skills`

### Tools

Baseline tools should help frontends use the configured backend predictably.

Initial tool categories:

1. provider connection helpers
2. runtime inspection helpers
3. safe sync or validation helpers where frontend-specific tooling needs them

Initial baseline tools:

1. `runtime-status`
2. `model-admin`

V1 sync should render baseline tool templates with the active profile defaults and place managed executable copies into the supported frontend-specific tool roots.

### Agents

Canonical shared agents are deferred until:

1. the runtime and profile model are stable
2. Codex, OpenCode, and OpenHands sync semantics are proven
3. the team has a clearer shared-agent authoring model

## 5. Content Source Policy

The repo remains the source of truth for shipped baseline content.

Source classes:

1. repo-authored content
2. selectively vendored external content

External references such as `superpowers`, StrongDM Factory, and skills from `skills.sh` may inform the catalog, but only intentionally adopted content should be vendored into this repo.

Adoption rules:

1. do not depend on upstream availability at runtime
2. record provenance for vendored content
3. keep the baseline catalog curated and small
4. push project-specific expansion into local installs rather than global sync

## 6. Sync Contract

Every frontend adapter must support:

1. active-profile provider wiring
2. managed baseline content sync
3. dry-run preview
4. explicit write mode
5. ownership tracking
6. idempotent repeated execution
7. preservation of unmanaged content

The operator experience should be:

1. select or activate a profile
2. preview sync
3. write sync
4. use the frontend immediately against the configured backend

## 7. Ownership And Precedence

Precedence model:

1. project-local installed skills
2. managed global baseline content
3. frontend defaults
4. unmanaged user custom content

Rules:

1. project-local installs are the preferred place for project-specific skills
2. global baseline content stays generic
3. sync must never overwrite unmanaged content silently
4. managed ownership must be explicit enough to support cleanup and later updates

## 8. Discovery And Project-Local Installs

`find-skills` is part of the baseline and the default discovery entry point.

Project-local install policy:

1. local-first by default
2. explicit target frontend selection
3. provenance captured for external content
4. global install of non-baseline content remains opt-in
5. in v1 this remains an external/manual workflow, not a native `aistackd` install command
6. for Codex and OpenCode, prefer `./.agents/skills/` for project-local additions so they stay distinct from the repo-managed baseline written by sync
7. for OpenHands, prefer `./.openhands/microagents/`; synced baseline microagents and unmanaged project-local additions may coexist there
8. adopted external skills may record provenance beside `SKILL.md` or the installed microagent in `aistackd-skill-provenance.json`

The goal is:

1. baseline content solves common work everywhere
2. project-specific content stays close to the project that needs it

## 9. Phase Deliverables

### Phase A: Catalog Foundation

1. baseline content inventory
2. source classification
3. provenance format for vendored content

### Phase B: Adapter Contracts

1. Codex adapter contract
2. OpenCode adapter contract
3. OpenHands adapter contract
4. ownership manifest shape

### Phase C: Sync Engine

1. dry-run output
2. write path
3. idempotency and unmanaged-content preservation

### Phase D: Discovery Workflow

1. baseline `find-skills`
2. project-local install flow documented around external/manual local-first installs
3. external content provenance tracking

## 10. Acceptance Criteria

This slice is complete for v1 when:

1. Codex, OpenCode, and OpenHands can be synced from an active profile without manual config editing
2. synced baseline skills and tools are usable immediately
3. unmanaged content survives repeated syncs
4. `find-skills` is available in the global baseline
5. project-specific additions can be installed locally without polluting the shared baseline
6. the project-local install flow is documented clearly without adding native package-management semantics to sync
