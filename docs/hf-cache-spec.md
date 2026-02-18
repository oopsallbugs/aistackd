# Hugging Face Snapshot Cache Spec

## Goal
Avoid repeated full snapshot fetches while remaining correct when repo revisions change.

## Runtime Location
- Cache file path: `./.ai_stack/huggingface/cache.json`
- Cache owner: `python_client/src/ai_stack/huggingface/cache.py`

## Schema
Current schema version: `1`.

```json
{
  "schema_version": 1,
  "updated_at": "...",
  "repos": {
    "namespace/repo@main": {
      "sha": "...",
      "last_checked": "...",
      "snapshot": {
        "repo_id": "namespace/repo",
        "revision": "main",
        "sha": "...",
        "last_modified": "...",
        "pipeline_tag": "...",
        "tags": [],
        "library_name": "...",
        "files": [
          {"path": "...", "size": 123, "lfs": {}}
        ]
      }
    }
  }
}
```

Key format is always `repo_id@revision`.

## Read/Write Behavior
- `get(repo_id, revision)`:
  - returns `CachedRepoSnapshot` when key exists and snapshot payload is valid.
  - returns `None` for missing key or malformed entry.
- `put(snapshot)`:
  - upserts by `repo_id@revision`.
  - sets `last_checked` and updates top-level `updated_at`.
- `touch(repo_id, revision)`:
  - updates `last_checked` only when entry exists.

## Schema Mismatch and Corruption Handling
On load:
- If file missing -> create fresh schema v1 cache.
- If JSON invalid -> recreate fresh schema v1 cache.
- If `schema_version` unsupported -> recreate fresh schema v1 cache.

No migration is attempted for unsupported schema versions.

## Orchestration Semantics (`stack/hf_downloads.py`)
For each repo/revision fetch:
1. `miss`: no cache entry, fetch full snapshot and store.
2. `hit`: cache exists and remote SHA unchanged, reuse snapshot.
3. `refresh`: cache exists and remote SHA changed (or local SHA missing while remote exists), refetch snapshot and store.
4. `fallback`: remote SHA lookup fails, reuse cached snapshot and update `last_checked`.

## Diagnostics and Observability
`SetupManager` tracks cache counters per process run:
- `miss`
- `hit`
- `refresh`
- `fallback`

CLI support:
- `download-model ... --cache-diagnostics` prints a per-run summary.
- List mode also supports diagnostics: `download-model <repo> --list --cache-diagnostics`.

Human-readable event lines are emitted via `SetupManager.format_cache_event(...)`.

## Constraints
- Cache stores serialized `RepoSnapshot` objects only.
- Cache does not select files; selection remains resolver responsibility.
- Cache does not own manifest/model state.
