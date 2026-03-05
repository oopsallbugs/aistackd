---
name: devops-platform-blueprint
description: Use this skill to design an implementation-ready platform delivery blueprint for environments, release flow, and operational safeguards.
---

# Devops Platform Blueprint

## Purpose
Use this skill to generate a platform delivery blueprint covering environments, deployment strategy, operations, and rollback readiness.

## When To Use
- Delivery flow needs to move from ad hoc execution to repeatable operation.
- Infrastructure and release decisions must be aligned before scaling usage.
- Teams need a concrete operational blueprint before implementation.

## Preconditions
- Service boundaries and runtime dependencies are known.
- Baseline security and reliability objectives are defined.
- Deployment ownership and support responsibilities are identified.

## Workflow
1. Define environment model:
   - local, integration, and production environment intent
   - environment-specific controls and guardrails
2. Select deployment strategy:
   - build, release, and promotion path
   - verification gates and rollback hooks
3. Specify secrets and configuration management approach:
   - storage and rotation policy
   - access boundaries
4. Define observability and incident model:
   - logs, metrics, tracing
   - alerting and incident response flow
5. Produce blueprint output package:
   - environment model
   - deployment strategy
   - secrets/config handling approach
   - observability/incident approach
   - rollback strategy
6. Add required control sections to the blueprint package:
   - Evidence Table (design claim, evidence source, confidence)
   - Owner + Due-by fields on every risk, safeguard, and follow-up action
   - What Would Change This Decision
7. Present outputs conversation-first; write files only when explicitly requested.

```bash
<map-environments> --service <service-id>
<design-release-flow> --service <service-id>
<define-secrets-model> --service <service-id>
<define-observability-model> --service <service-id>
```

For checklists and pattern guidance, read:
- `references/platform-blueprint-checklist.md`
- `references/release-rollback-patterns.md`

## Failure Triage
- Blueprint is conceptual but not actionable:
  - add owners, sequence, and verification gates.
- Deployment strategy is risky:
  - enforce pre-release checks and rollback trigger conditions.
- Secrets handling is incomplete:
  - define storage, rotation cadence, and access policy.
- Incident model lacks accountability:
  - assign on-call ownership and escalation timelines.

## Boundaries
- Keep language strictly agent-neutral.
- Keep default behavior conversation-first and artifact-oriented.
- Do not approve rollout without rollback and incident response coverage.
- Do not collapse environment responsibilities into a single undefined stage.
