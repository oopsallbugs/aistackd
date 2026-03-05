# Platform Blueprint Checklist

Use this checklist to verify the blueprint is implementation ready.

## Environment Model
- Environment list and purpose are explicit.
- Promotion path between environments is clear.
- Environment-specific risk controls are defined.

## Release Strategy
- Build, test, and deploy sequence is documented.
- Release gates are measurable.
- Rollback triggers and execution steps are explicit.

## Security And Configuration
- Secrets storage and rotation policy are defined.
- Access model follows least privilege.
- Configuration drift detection is addressed.

## Observability And Operations
- Logging, metrics, and tracing coverage is defined.
- Alerting thresholds and ownership are clear.
- Incident response and escalation flow are documented.
- Minimum observability signal set is defined:
  - stale ADR links
  - missing owner or due-by on risks/blockers
  - phase status mismatch between roadmap and phase docs
  - missing explicit out-of-scope section in active phase plan

## Evidence Table
- Include a table with:
  - design claim
  - evidence source
  - confidence (High/Med/Low)

## Ownership And Due Dates
- Every safeguard, risk treatment, and follow-up action has:
  - Owner
  - Due-by

## What Would Change This Decision
- Triggers that require redesign of environment model or release strategy are explicit.

## Chat-Friendly Report Format
When presenting checklist outcomes in chat, use numbered control results:

1. `Control: <name>` `Status: <pass/fail/partial>`
- `Evidence:`
- `Owner:`
- `Due-by:`
