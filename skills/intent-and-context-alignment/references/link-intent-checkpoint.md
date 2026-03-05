# Link Intent Checkpoint

## Rationale
When a request includes a link but does not define expected output or project relation, fetch-first behavior can waste effort and create misalignment. A short intent checkpoint keeps the flow local-first, confirms relevance, and asks one high-impact question before any external fetch attempt.

## Reusable Prompt Variants
1. "Based on what I can see in this repo: `<context findings>`. From this alone, I cannot yet confirm this link is useful for `<project objective>`. How do you want this to fit: replace existing components, augment them, or evaluate only?"
2. "Current repo context suggests `<constraints or gaps>`. I can/cannot determine relevance of `<link>` from local evidence alone. What role should this link play in your plan?"
3. "I found `<local findings>`, and the link may be relevant to `<possible intent>`, but intent is still unverified. Should I treat it as a replacement path, an integration option, or background research?"

## Decision Table
| Intent clarity | Network availability | Required next action |
| --- | --- | --- |
| Clear intent | Allowed | Proceed to external evidence collection if needed. |
| Clear intent | Blocked | Report limitation, continue with local evidence, request user-provided excerpts if needed. |
| Unclear intent | Allowed | Do not fetch yet. Run intent checkpoint and ask one high-impact question. |
| Unclear intent | Blocked | Do not fetch. Run intent checkpoint with local findings and request intended use or excerpts. |
