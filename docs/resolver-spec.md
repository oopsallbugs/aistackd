# Resolver Spec

> Legacy note (March 2, 2026): the public runtime CLI moved to `bootstrap-stack`. This document remains reference material for the prior direct HF resolver flow.

## Scope
Resolver logic is implemented in `python_client/src/ai_stack/huggingface/resolver.py`.

The resolver is responsible for selecting files from an already-fetched `RepoSnapshot`.
It does not perform network calls and does not update manifest state.

## Inputs
- `RepoSnapshot`
  - `files`
  - derived views: `gguf_files`, `mmproj_files`
- `preferred_quants: list[str]`
  - caller-provided quant preferences, including CLI `--quant`.

## Outputs
- `ResolvedDownload`
  - `repo_id`
  - `revision`
  - `sha`
  - `model_file`
  - `mmproj_file` (optional)

## Quant Parsing
`parse_quant_from_filename(path)` extracts quant tokens from GGUF filenames using ordered regex patterns:
1. `IQ\d+_[A-Z0-9_]+`
2. `Q\d+_[A-Z0-9_]+`
3. `Q\d+_\d+`
4. `Q\d+`

Example matches:
- `model-IQ4_NL.gguf` -> `IQ4_NL`
- `model-Q4_K_M.gguf` -> `Q4_K_M`
- `model-Q8_0.gguf` -> `Q8_0`

## Ranking and Selection
Default fallback ranking is `DEFAULT_QUANT_RANKING`:
1. `IQ4_NL`
2. `Q4_K_M`
3. `Q5_K_M`
4. `Q8_0`
5. `Q4_0`
6. `Q3_K_M`
7. `Q2_K`

Selection algorithm (`pick_gguf_file`):
1. Filter GGUF candidates from snapshot.
2. Apply explicit preferred quants first (exact parsed quant or filename substring match).
3. If no explicit match, sort by ranked quant position, then filename.
4. If still ambiguous, fallback to first filename containing `Q4`.
5. Final fallback: first GGUF file.

Failure mode:
- If no GGUF files exist, raise `ValueError("No GGUF files found in repo ...")`.

## Explicit `--quant` Behavior
CLI `download-model --quant Q5_K_M ...` passes quant preference through orchestration:
- `download.py` -> `SetupManager.download_from_huggingface(..., quant_preference=...)`
- `hf_downloads.download_from_huggingface()` prepends explicit quant to preferred list
- resolver evaluates explicit quant before ranked fallback.

## mmproj Selection
`pick_mmproj_file(snapshot)` returns:
- first entry in `snapshot.mmproj_files`, or
- `None` when no mmproj files are present.

Current behavior is intentionally simple; pairing refinement remains a future enhancement.

## Non-Goals
- No HF transport calls.
- No manifest writes.
- No model metadata enrichment.

## Architecture Guardrail
Resolver remains decision-only logic and is composed by orchestration (`stack/hf_downloads.py` and `SetupManager`).
