# Release And Rollback Patterns

Use these patterns to choose a release approach with controlled risk.

## Common Release Patterns
- Rolling update
- Blue/green
- Canary
- Feature-flag gated release

## Pattern Selection Prompts
- What is acceptable user impact during release.
- How quickly must rollback complete.
- What verification signal is trusted for go/no-go.
- What operational load can the team sustain.

## Rollback Design Basics
- Define clear rollback triggers.
- Keep rollback path version-compatible.
- Ensure rollback can be executed without manual invention.
- Verify rollback path in pre-release validation.

## Minimum Rollout Safeguards
- Pre-release health checks.
- Post-release validation window.
- Alert ownership during release window.
- Incident handoff protocol if release degrades service.
