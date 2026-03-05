---
name: intent-and-context-alignment
description: Use this skill when intent is unclear and you need to gather evidence, surface assumptions early, and align outputs with user goals before planning or drafting.
---

# Intent And Context Alignment

## Purpose
Use this skill to reduce ambiguity before planning or documentation by collecting evidence, validating assumptions, and aligning on target outcomes.

## When To Use
- The request is broad or under-specified.
- User goals are implied but not explicit.
- A link or external reference is provided without clear expected output.
- A user shares an external link and asks for evaluation without describing intended project role.
- There is risk of producing a plan from unverified assumptions.
- Multiple interpretations could lead to different decisions.

## Preconditions
- You can inspect available project context or provided artifacts.
- You can identify what is known, unknown, and inferred.
- You can ask focused follow-up questions when gaps materially affect outcomes.

## Workflow
1. Capture the initial request and extract candidate intents.
2. Run local-context discovery on the highest-impact unknowns first:
   - current state
   - constraints
   - success target
   - compatibility risks
3. Build an assumptions ledger:
   - verified assumptions
   - unverified assumptions
   - rejected assumptions
4. Run the intent checkpoint before external fetch:
   - provide concise local findings
   - state whether link relevance is determinable yet
   - ask one direct, high-impact question about intended use
5. Only after user confirmation, collect external evidence when needed and allowed.
6. Produce the alignment package:
   - clarified goal statement
   - evidence table
   - assumptions ledger
   - open questions ranked by impact
   - recommended next-step path
   - top 3 unknowns still open
7. Add required control sections:
   - Evidence Table (claim, evidence source, confidence)
   - Owner + Due-by for open questions and follow-up actions
   - What Would Change This Direction
8. Keep output conversation-first; write files only when explicitly requested.

## Link Handling Policy
- Default:
  - local-first; do not auto-download external resources.
- Gate:
  - do not fetch external content until the intent checkpoint passes when ambiguity is material.
- Blocked network:
  - continue with local evidence and ask for intended use or user-provided excerpts.
- Escalation:
  - if fetch is required, ask for explicit permission before attempting clone/curl/wget/browse/API retrieval.

## Pre-Fetch Clarification Prompt
Use this prompt shape for link-only or ambiguous link requests before external fetch:
- "Based on what I can see in this repo: <context findings>."
- "From this alone, I can/cannot confirm this link is useful for <project objective>."
- "How do you want this to fit: replace existing components, augment them, or evaluate only?"

For additional prompt variants and decision logic, read:
- `references/link-intent-checkpoint.md`

```bash
<extract-intent-candidates> --request <request-id>
<collect-context-evidence> --scope <scope-id>
<build-assumption-ledger> --context <context-id>
<rank-open-questions> --impact-model <model-id>
```

For templates and checks, read:
- `references/assumption-ledger-template.md`
- `references/question-prioritization.md`

## Failure Triage
- You still cannot infer user intent:
  - ask one direct, high-impact clarification question.
- If link is provided but intent remains unclear:
  - do not fetch; run the intent checkpoint and ask one high-impact clarification question.
- Too much context is collected without progress:
  - stop and prioritize unknowns by decision impact.
- Assumptions are mixed with facts:
  - separate into verified and unverified with evidence links.
- Output is informative but not actionable:
  - add clear recommended next-step path and ownership.

## Boundaries
- Do not finalize plans while critical unknowns remain unresolved.
- Do not treat unverified assumptions as facts.
- Do not perform external fetch/download for ambiguous link-only requests before the intent checkpoint.
- Keep language strictly agent-neutral.
- Keep the process concise and avoid context bloat.
