---
name: architecture-options-evaluator
description: Use this skill to evaluate competing architecture options and produce a decision package with clear tradeoffs.
---

# Architecture Options Evaluator

## Purpose
Use this skill to compare multiple architecture approaches and select one with explicit scoring, rationale, and risk treatment.

## When To Use
- Multiple architecture directions are viable.
- A high-impact decision must be made before implementation.
- A prior decision needs re-evaluation due to new constraints.

## Preconditions
- The decision question is explicitly stated.
- At least two viable options are defined.
- Evaluation criteria and constraints are available.

## Workflow
1. Frame the decision:
   - decision statement
   - constraints
   - non-negotiable requirements
2. Build options matrix:
   - list options and assumptions
   - evaluate each option against criteria
3. Score and analyze:
   - record scoring rationale
   - identify strongest and weakest conditions per option
4. Produce decision package:
   - options matrix
   - scoring rationale
   - selected option
   - rejected options with reasons
   - decision risks and mitigations
5. Add required control sections to the decision package:
   - Evidence Table (decision claim, evidence source, confidence)
   - Owner + Due-by fields on every risk and mitigation action
   - What Would Change This Decision
6. Present outputs conversation-first; write files only when explicitly requested.

```bash
<define-decision-question> --id <decision-id>
<build-options-matrix> --decision <decision-id>
<score-options> --matrix <matrix-id>
<select-option> --matrix <matrix-id> --criteria <criteria-set>
```

For templates and checks, read:
- `references/options-matrix.md`
- `references/decision-quality-checks.md`

## Failure Triage
- Options are too similar:
  - refine option boundaries and assumptions until differences are testable.
- Scores look arbitrary:
  - require criterion-by-criterion evidence notes for each score.
- Decision remains unclear:
  - run sensitivity check on top two criteria and reassess.
- Risk coverage is weak:
  - add failure modes and fallback plans for the selected option.

## Boundaries
- Keep analysis strictly agent-neutral.
- Require at least two real options before selecting.
- Keep default behavior conversation-first and artifact-oriented.
- Do not recommend an option without explicit rejected-option reasoning.
