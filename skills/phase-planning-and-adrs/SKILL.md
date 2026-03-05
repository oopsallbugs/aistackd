---
name: phase-planning-and-adrs
description: Use this skill to produce decision-complete phase plans and ADR candidate sets from active project context.
---

# Phase Planning And ADRs

## Purpose
Use this skill to create a phase plan that is decision complete and coupled to explicit architecture decision records.

## When To Use
- A new phase is being prepared.
- Phase scope needs to be reset after new constraints or learnings.
- Large decisions need formal ADR candidates before implementation starts.

## Preconditions
- Project context is available (codebase, existing plans, and delivery constraints).
- A target phase window exists (for example `Phase E`).
- Decision owners and review stakeholders are identified.
- If intent or target outcomes are unclear, run `intent-and-context-alignment` first.

## Workflow
1. Gather current-state context and constraints:
   - system boundaries
   - delivery risks
   - dependencies and sequencing pressure
2. Define the phase frame:
   - phase goal statement
   - in-scope and out-of-scope items
   - measurable acceptance gates
3. Draft ADR candidates for decisions with high impact:
   - architecture boundary changes
   - public interface shifts
   - platform or operational policy changes
4. Build the decision-complete output package:
   - phase goals
   - in/out scope
   - ADR candidates
   - acceptance gates
   - risks and mitigations
5. Add required control sections to the output package:
   - Evidence Table (claim, evidence source, confidence)
   - Owner + Due-by fields on every risk, mitigation, blocker, and gate
   - What Would Change This Decision
6. Present outputs conversation-first; write files only when explicitly requested.

```bash
<collect-project-context> --phase <phase-id>
<draft-phase-plan> --from-context <context-id>
<derive-adr-candidates> --plan <plan-id>
<review-risk-register> --plan <plan-id>
```

For reusable templates, read:
- `references/phase-plan-outline.md`
- `references/adr-lifecycle.md`

## Failure Triage
- Scope keeps expanding:
  - reduce to milestone-level deliverables and defer non-critical items explicitly.
- ADR list is too large:
  - prioritize by irreversible impact and operational risk.
- Acceptance criteria are vague:
  - rewrite as binary checks with observable evidence.
- Stakeholder alignment is weak:
  - identify unresolved decisions and require explicit owner sign-off.

## Boundaries
- Keep guidance strictly agent-neutral.
- Keep default behavior conversation-first and artifact-oriented.
- Do not mutate project files unless the user explicitly requests file creation or edits.
- Do not finalize phase scope without explicit deferred-item listing.
